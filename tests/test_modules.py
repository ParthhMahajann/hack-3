"""
Tests for nlp_summarizer, ml_risk_predictor, and incentive_calculator.
These modules had no automated tests prior to this file.
"""
import pytest
from backend.core.nlp_summarizer import summarise_visit


class TestNLPSummarizer:

    def test_maternal_purple_summary(self):
        """PURPLE risk → summary_en contains emergency text, urgency == 'purple'."""
        result = summarise_visit(
            "maternal",
            {"hemoglobin": 6.0, "systolic_bp": 165, "diastolic_bp": 112},
            {"edema_generalised": True, "proteinuria_2plus": True},
            "purple", 85,
        )
        assert result["urgency"] == "purple"
        assert "EMERGENCY" in result["summary_en"]

    def test_maternal_green_summary(self):
        """GREEN risk → urgency == 'green', recommendation contains 'Routine'."""
        result = summarise_visit(
            "maternal",
            {"hemoglobin": 12.0, "systolic_bp": 110, "diastolic_bp": 70},
            {},
            "green", 10,
        )
        assert result["urgency"] == "green"
        assert "Routine" in result["recommendation_en"]

    def test_child_danger_sign_summary(self):
        """IMNCI danger sign → summary_en contains 'IMMEDIATE'."""
        result = summarise_visit(
            "child",
            {"muac_mm": 130},
            {"danger_signs": ["convulsions"]},
            "purple", 100,
        )
        assert "IMMEDIATE" in result["summary_en"]

    def test_bilingual_keys_present(self):
        """lang='both' (default) → all bilingual keys present in output."""
        result = summarise_visit(
            "maternal",
            {"hemoglobin": 9.5, "systolic_bp": 130, "diastolic_bp": 80},
            {},
            "yellow", 35,
        )
        assert "summary_en" in result
        assert "summary_hi" in result
        assert "key_findings_hi" in result

    def test_ml_forecast_line_included(self):
        """ml_forecast dict passed → ml_forecast field contains the percentage."""
        result = summarise_visit(
            "maternal",
            {"hemoglobin": 6.5, "systolic_bp": 155, "diastolic_bp": 100},
            {},
            "red", 65,
            ml_forecast={"percentage": 72.3},
            lang="en",
        )
        assert "72.3" in result["ml_forecast"]


from backend.core.ml_risk_predictor import (
    MaternalMLInput, ChildMLInput,
    predict_maternal_risk, predict_child_risk,
)


class TestMLRiskPredictor:

    def test_healthy_maternal_lower_probability_than_high_risk(self):
        """Normal vitals → lower 30-day probability than a pre-eclampsia case."""
        healthy = MaternalMLInput(
            hemoglobin=12.0, systolic_bp=110, diastolic_bp=70,
            gestational_week=20, age=25,
        )
        sick = MaternalMLInput(
            hemoglobin=8.0, systolic_bp=162, diastolic_bp=112,
            gestational_week=32, age=28,
            edema=True, proteinuria=True, prev_complications=True,
        )
        p_healthy = predict_maternal_risk(healthy)["probability_30d"]
        p_sick = predict_maternal_risk(sick)["probability_30d"]
        assert p_healthy < p_sick

    def test_preeclampsia_maternal_high_probability(self):
        """Severe BP + oedema + proteinuria + low Hb → probability > 0.5."""
        data = MaternalMLInput(
            hemoglobin=8.0, systolic_bp=162, diastolic_bp=112,
            gestational_week=32, age=28,
            edema=True, proteinuria=True, prev_complications=True,
        )
        result = predict_maternal_risk(data)
        assert result["probability_30d"] > 0.5

    def test_predict_child_returns_required_keys(self):
        """Child prediction returns all expected response keys."""
        data = ChildMLInput(muac_mm=120, waz_score=-2.5, age_months=18)
        result = predict_child_risk(data)
        for key in ("probability_30d", "percentage", "risk_band", "top_factors", "interpretation"):
            assert key in result, f"Missing key: {key}"

    def test_top_factors_returned(self):
        """High-risk maternal case → top_factors is a non-empty list of strings."""
        data = MaternalMLInput(
            hemoglobin=6.0, systolic_bp=155, diastolic_bp=100,
            gestational_week=30, age=19,
            edema=True, proteinuria=True,
        )
        result = predict_maternal_risk(data)
        assert isinstance(result["top_factors"], list)
        assert len(result["top_factors"]) > 0

    def test_probability_bounded(self):
        """Probability is always in [0.0, 1.0] regardless of extreme inputs."""
        data = MaternalMLInput(
            hemoglobin=2.0, systolic_bp=220, diastolic_bp=140,
            gestational_week=40, age=14,
            edema=True, proteinuria=True, prev_complications=True,
            missed_anc_visits=8,
        )
        result = predict_maternal_risk(data)
        assert 0.0 <= result["probability_30d"] <= 1.0


from backend.core.incentive_calculator import (
    calculate_incentives_from_visit, summarise_incentives,
    IncentiveType,
)

_PATIENT = {"id": "p-test", "name": "Test Patient"}


class TestIncentiveCalculator:

    def test_rural_delivery_incentive(self):
        """Institutional delivery in rural area → ₹1400 (JSY rural rate, MOHFW 2015)."""
        events = calculate_incentives_from_visit(
            "delivery",
            {"delivery_place": "institution", "visit_date": "2025-04-29"},
            _PATIENT,
            is_rural=True,
        )
        assert len(events) == 1
        assert events[0].amount == 1400
        assert events[0].type == IncentiveType.JSY_INSTITUTIONAL_DELIVERY_RURAL

    def test_urban_delivery_incentive(self):
        """Institutional delivery in urban area → ₹1000 (JSY urban rate, MOHFW 2015)."""
        events = calculate_incentives_from_visit(
            "delivery",
            {"delivery_place": "institution", "visit_date": "2025-04-29"},
            _PATIENT,
            is_rural=False,
        )
        assert len(events) == 1
        assert events[0].amount == 1000
        assert events[0].type == IncentiveType.JSY_INSTITUTIONAL_DELIVERY_URBAN

    def test_anc_registration_incentive(self):
        """ANC registration visit → ₹300 incentive (JSY/JSSK guideline)."""
        events = calculate_incentives_from_visit(
            "anc_registration",
            {"visit_date": "2025-04-29"},
            _PATIENT,
        )
        assert any(e.type == IncentiveType.ANC_REGISTRATION for e in events)
        assert any(e.amount == 300 for e in events)

    def test_vaccine_bcg_incentive(self):
        """BCG vaccine given → ₹150 immunisation incentive."""
        events = calculate_incentives_from_visit(
            "home_visit",
            {"vaccines_given": ["bcg"], "visit_date": "2025-04-29"},
            _PATIENT,
        )
        assert any(e.type == IncentiveType.IMMUNISATION_BCG for e in events)
        assert any(e.amount == 150 for e in events)

    def test_summarise_incentives_totals(self):
        """summarise_incentives correctly totals earned, verified, and pending."""
        events_data = [
            {"type": "jsy_delivery_rural", "amount": 1400, "verified": True},
            {"type": "anc_registration", "amount": 300, "verified": False},
        ]
        summary = summarise_incentives(events_data)
        assert summary["total_earned"] == 1700
        assert summary["total_verified"] == 1400
        assert summary["pending_payment"] == 300
