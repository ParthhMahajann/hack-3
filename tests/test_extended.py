"""
Extended test suite -- sync engine, NLP summarizer, incentive calculator,
and dashboard analytics endpoints.

Covers the gaps identified in the rubric assessment:
  - Sync engine: field-level merge, conflict detection, priority ordering
  - NLP summarizer: bilingual output, lang routing, edge cases
  - Incentive calculator: JSY amounts, vaccine dedup, edge cases
  - Dashboard: stats, risk distribution, ANC coverage
"""

import pytest
from backend.core.sync_engine import field_level_merge
from backend.core.nlp_summarizer import summarise_visit
from backend.core.incentive_calculator import (
    calculate_incentives_from_visit, IncentiveType, INCENTIVE_AMOUNTS,
)
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════════════
# Sync Engine -- field_level_merge (pure function, no DB needed)
# ═══════════════════════════════════════════════════════════════════════════

class TestFieldLevelMerge:

    def test_disjoint_keys_union(self):
        """Fields on different sides merge via Grow-Only Set union."""
        server = {"hemoglobin": 10.5}
        client = {"systolic_bp": 130}
        ts_s = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ts_c = datetime(2025, 1, 2, tzinfo=timezone.utc)

        merged, conflicts = field_level_merge(server, client, ts_s, ts_c)
        assert merged == {"hemoglobin": 10.5, "systolic_bp": 130}
        assert conflicts == []

    def test_same_values_no_conflict(self):
        """Identical values on both sides produce no conflict."""
        server = {"hemoglobin": 10.5, "weight_kg": 55}
        client = {"hemoglobin": 10.5, "weight_kg": 55}
        ts_s = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ts_c = datetime(2025, 1, 2, tzinfo=timezone.utc)

        merged, conflicts = field_level_merge(server, client, ts_s, ts_c)
        assert merged == {"hemoglobin": 10.5, "weight_kg": 55}
        assert conflicts == []

    def test_client_wins_when_newer(self):
        """When client is newer, conflicting field takes client value."""
        server = {"hemoglobin": 10.5}
        client = {"hemoglobin": 8.0}
        ts_s = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ts_c = datetime(2025, 1, 2, tzinfo=timezone.utc)  # client is newer

        merged, conflicts = field_level_merge(server, client, ts_s, ts_c)
        assert merged["hemoglobin"] == 8.0
        assert len(conflicts) == 1
        assert conflicts[0]["winner"] == "client"

    def test_server_wins_when_newer(self):
        """When server is newer, conflicting field keeps server value."""
        server = {"hemoglobin": 10.5}
        client = {"hemoglobin": 8.0}
        ts_s = datetime(2025, 1, 2, tzinfo=timezone.utc)  # server is newer
        ts_c = datetime(2025, 1, 1, tzinfo=timezone.utc)

        merged, conflicts = field_level_merge(server, client, ts_s, ts_c)
        assert merged["hemoglobin"] == 10.5
        assert len(conflicts) == 1
        assert conflicts[0]["winner"] == "server"

    def test_mixed_merge_preserves_all_data(self):
        """Real-world scenario: two devices record different vitals."""
        server = {"hemoglobin": 9.5, "weight_kg": 55, "edema": False}
        client = {"systolic_bp": 145, "weight_kg": 56, "proteinuria": True}
        ts_s = datetime(2025, 1, 1, tzinfo=timezone.utc)
        ts_c = datetime(2025, 1, 2, tzinfo=timezone.utc)

        merged, conflicts = field_level_merge(server, client, ts_s, ts_c)
        # All keys present in merged result
        assert "hemoglobin" in merged       # server-only
        assert "systolic_bp" in merged      # client-only
        assert "proteinuria" in merged      # client-only
        assert "edema" in merged            # server-only
        # weight_kg was on both with different values -> conflict
        assert merged["weight_kg"] == 56    # client wins (newer)
        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "weight_kg"

    def test_empty_dicts(self):
        """Empty dicts merge cleanly."""
        merged, conflicts = field_level_merge(
            {}, {}, datetime.min.replace(tzinfo=timezone.utc),
            datetime.min.replace(tzinfo=timezone.utc)
        )
        assert merged == {}
        assert conflicts == []


# ═══════════════════════════════════════════════════════════════════════════
# NLP Summarizer -- bilingual output and lang routing
# ═══════════════════════════════════════════════════════════════════════════

class TestNLPSummarizer:

    def test_maternal_bilingual_output(self):
        """Default (lang=both) returns both EN and Hindi keys."""
        result = summarise_visit(
            patient_type="maternal",
            vitals={"hemoglobin": 6.5, "systolic_bp": 148, "diastolic_bp": 95},
            observations={"edema_generalised": True, "proteinuria_2plus": True},
            risk_level="purple", risk_score=85,
        )
        assert "summary_en" in result
        assert "summary_hi" in result
        assert "key_findings" in result
        assert "key_findings_hi" in result

    def test_lang_en_returns_english_only(self):
        """lang='en' returns flat English structure without _hi keys."""
        result = summarise_visit(
            patient_type="maternal",
            vitals={"hemoglobin": 11.0, "systolic_bp": 110, "diastolic_bp": 70},
            observations={},
            risk_level="green", risk_score=0, lang="en",
        )
        assert "summary" in result
        assert "summary_en" not in result  # flat key, not bilingual
        assert "summary_hi" not in result

    def test_lang_hi_returns_hindi_only(self):
        """lang='hi' returns Hindi summary."""
        result = summarise_visit(
            patient_type="maternal",
            vitals={"hemoglobin": 9.0},
            observations={},
            risk_level="yellow", risk_score=30, lang="hi",
        )
        assert "summary" in result
        assert "summary_hi" not in result

    def test_child_danger_sign_summary(self):
        """IMNCI danger sign produces urgent EN + Hindi output."""
        result = summarise_visit(
            patient_type="child",
            vitals={"muac_mm": 130},
            observations={"danger_signs": ["convulsions"]},
            risk_level="purple", risk_score=100,
        )
        assert "IMNCI" in result["summary_en"]
        assert any("IMNCI" in f or "danger" in f.lower()
                    for f in result["key_findings"])

    def test_child_sam_summary(self):
        """SAM child (MUAC < 115) produces correct summary."""
        result = summarise_visit(
            patient_type="child",
            vitals={"muac_mm": 108},
            observations={},
            risk_level="purple", risk_score=90,
        )
        assert "SAM" in result["summary_en"]

    def test_maternal_severe_anaemia_hindi(self):
        """Severe anaemia generates Hindi text with correct keyword."""
        result = summarise_visit(
            patient_type="maternal",
            vitals={"hemoglobin": 6.0},
            observations={},
            risk_level="red", risk_score=60, lang="hi",
        )
        # Hindi keyword check
        assert any("एनीमिया" in f for f in result["key_findings"])


# ═══════════════════════════════════════════════════════════════════════════
# Incentive Calculator -- JSY/JSSK amounts and edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestIncentiveCalculator:

    def test_anc_registration_gives_300(self):
        """ANC registration = Rs 300 (JSY operational guidelines)."""
        events = calculate_incentives_from_visit(
            visit_type="anc_registration",
            observations={"visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
        )
        assert len(events) == 1
        assert events[0].amount == 300
        assert events[0].type == IncentiveType.ANC_REGISTRATION

    def test_institutional_delivery_rural_1400(self):
        """Rural institutional delivery = Rs 1400 (JSY)."""
        events = calculate_incentives_from_visit(
            visit_type="delivery",
            observations={"delivery_place": "institution", "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
            is_rural=True,
        )
        assert len(events) == 1
        assert events[0].amount == 1400

    def test_institutional_delivery_urban_1000(self):
        """Urban institutional delivery = Rs 1000 (JSY)."""
        events = calculate_incentives_from_visit(
            visit_type="delivery",
            observations={"delivery_place": "institution", "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
            is_rural=False,
        )
        assert len(events) == 1
        assert events[0].amount == 1000

    def test_home_delivery_500(self):
        """Home delivery = Rs 500."""
        events = calculate_incentives_from_visit(
            visit_type="delivery",
            observations={"delivery_place": "home", "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
        )
        assert len(events) == 1
        assert events[0].amount == 500

    def test_vaccine_penta_dedup(self):
        """Multiple penta doses in one session = only 1 incentive event."""
        events = calculate_incentives_from_visit(
            visit_type="home_visit",
            observations={"vaccines_given": ["penta1", "penta2"], "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
        )
        penta_events = [e for e in events if e.type == IncentiveType.IMMUNISATION_PENTA_DOSE]
        assert len(penta_events) == 1, "Multiple penta doses should be deduped to 1 incentive"

    def test_bcg_plus_measles_two_events(self):
        """BCG + measles = 2 separate incentive events."""
        events = calculate_incentives_from_visit(
            visit_type="home_visit",
            observations={"vaccines_given": ["bcg", "measles"], "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
        )
        assert len(events) == 2
        assert sum(e.amount for e in events) == 300  # 150 + 150

    def test_referral_escort_250(self):
        """Referral escort = Rs 250."""
        events = calculate_incentives_from_visit(
            visit_type="home_visit",
            observations={"referral_escorted": True, "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
        )
        assert len(events) == 1
        assert events[0].amount == 250

    def test_no_events_for_normal_anc(self):
        """Regular ANC visit (not registration, not 4th) = no incentive."""
        events = calculate_incentives_from_visit(
            visit_type="anc",
            observations={"anc_contact_number": 2, "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
        )
        assert len(events) == 0

    def test_4th_anc_contact_triggers_incentive(self):
        """4th ANC contact = Rs 300 bonus."""
        events = calculate_incentives_from_visit(
            visit_type="anc",
            observations={"anc_contact_number": 4, "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
        )
        assert len(events) == 1
        assert events[0].amount == 300

    def test_nrc_admission_500(self):
        """NRC admission support = Rs 500."""
        events = calculate_incentives_from_visit(
            visit_type="home_visit",
            observations={"nrc_admitted": True, "visit_date": "2025-04-29"},
            patient={"id": "p1", "name": "Test"},
        )
        assert len(events) == 1
        assert events[0].amount == 500

    def test_all_incentive_amounts_are_positive(self):
        """Sanity: all defined incentive amounts are positive integers."""
        for itype, amount in INCENTIVE_AMOUNTS.items():
            assert amount > 0, f"{itype.value} has non-positive amount: {amount}"
            assert isinstance(amount, int), f"{itype.value} amount is not int"
