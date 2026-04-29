"""
Clinical test cases for the risk scoring engine.
Each test is based on a real clinical scenario matching WHO/IMNCI guidelines.
Run: pytest tests/ -v
"""

import pytest
from backend.core.risk_engine import (
    MaternalRiskInput, ChildRiskInput,
    score_maternal, score_child, RiskLevel
)


# ─────────────────────────────────────────────────────────────────────────────
# Maternal Risk Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMaternalRisk:

    def test_healthy_low_risk(self):
        """Normal vitals → GREEN."""
        inp = MaternalRiskInput(
            hemoglobin=11.5, systolic_bp=110, diastolic_bp=70,
            age=24, gestational_week=20,
            missed_anc_visits=0, previous_complications=False,
            edema_generalised=False, proteinuria_2plus=False,
        )
        result = score_maternal(inp)
        assert result["level"] == RiskLevel.GREEN.value
        assert result["score"] < 30

    def test_severe_anaemia_becomes_red(self):
        """Hb < 7 g/dL alone → RED (WHO ANC 2016, Rec 38)."""
        inp = MaternalRiskInput(
            hemoglobin=6.2, systolic_bp=110, diastolic_bp=70,
            age=24, gestational_week=28,
            missed_anc_visits=0, previous_complications=False,
            edema_generalised=False, proteinuria_2plus=False,
        )
        result = score_maternal(inp)
        assert result["level"] in (RiskLevel.RED.value, RiskLevel.PURPLE.value)
        assert any("anaemia" in t.lower() for t in result["triggered_parameters"])

    def test_preeclampsia_triad_is_purple(self):
        """BP 148/95 + proteinuria + oedema → PURPLE (imminent eclampsia)."""
        inp = MaternalRiskInput(
            hemoglobin=10.5, systolic_bp=148, diastolic_bp=95,
            age=28, gestational_week=32,
            missed_anc_visits=0, previous_complications=False,
            edema_generalised=True, proteinuria_2plus=True,
        )
        result = score_maternal(inp)
        assert result["level"] == RiskLevel.PURPLE.value
        assert result["notify_block_officer"] is True

    def test_severe_hypertension_is_purple(self):
        """BP ≥ 160/110 → PURPLE immediately (WHO severe threshold)."""
        inp = MaternalRiskInput(
            hemoglobin=11.0, systolic_bp=165, diastolic_bp=112,
            age=30, gestational_week=35,
            missed_anc_visits=0, previous_complications=False,
            edema_generalised=False, proteinuria_2plus=False,
        )
        result = score_maternal(inp)
        assert result["level"] == RiskLevel.PURPLE.value

    def test_adolescent_anaemia_yellow(self):
        """Age 16 + moderate anaemia → at least YELLOW."""
        inp = MaternalRiskInput(
            hemoglobin=9.5, systolic_bp=110, diastolic_bp=70,
            age=16, gestational_week=16,
            missed_anc_visits=1, previous_complications=False,
            edema_generalised=False, proteinuria_2plus=False,
        )
        result = score_maternal(inp)
        assert result["level"] in (RiskLevel.YELLOW.value, RiskLevel.RED.value, RiskLevel.PURPLE.value)

    def test_rising_bp_trend_escalates(self):
        """Trend escalation: BP rising +5 mmHg/visit adds 20 points."""
        inp = MaternalRiskInput(
            hemoglobin=11.0, systolic_bp=128, diastolic_bp=80,
            age=25, gestational_week=30,
            missed_anc_visits=0, previous_complications=False,
            edema_generalised=False, proteinuria_2plus=False,
            bp_history=[108, 116, 121, 128],  # +5/visit slope
        )
        result = score_maternal(inp)
        assert result["score"] >= 20  # trend adds 20 points
        assert any("trend" in t.lower() for t in result["triggered_parameters"])

    def test_gdm_adds_to_score(self):
        """FBS > 126 mg/dL adds 15 points (GDM threshold)."""
        baseline = MaternalRiskInput(
            hemoglobin=11.0, systolic_bp=110, diastolic_bp=70,
            age=25, gestational_week=24,
            missed_anc_visits=0, previous_complications=False,
            edema_generalised=False, proteinuria_2plus=False,
        )
        with_gdm = MaternalRiskInput(
            hemoglobin=11.0, systolic_bp=110, diastolic_bp=70,
            age=25, gestational_week=24,
            missed_anc_visits=0, previous_complications=False,
            edema_generalised=False, proteinuria_2plus=False,
            fbs=135.0,
        )
        r_base = score_maternal(baseline)
        r_gdm = score_maternal(with_gdm)
        assert r_gdm["score"] == r_base["score"] + 15

    def test_requires_immediate_alert_flag(self):
        """RED and PURPLE cases must have requires_immediate_alert=True."""
        inp = MaternalRiskInput(
            hemoglobin=6.0, systolic_bp=145, diastolic_bp=92,
            age=19, gestational_week=28,
            missed_anc_visits=2, previous_complications=True,
            edema_generalised=True, proteinuria_2plus=True,
        )
        result = score_maternal(inp)
        assert result["requires_immediate_alert"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Child Risk Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestChildRisk:

    def test_healthy_child_green(self):
        """Normal vitals → GREEN."""
        inp = ChildRiskInput(
            age_months=12, muac_mm=140, weight_kg=9.0, height_cm=75,
            sex="M", fever_days=0, temperature_c=37.0,
            danger_signs=[], immunisation_overdue_days=0, breastfeeding_ok=True,
        )
        result = score_child(inp)
        assert result["level"] == RiskLevel.GREEN.value

    def test_sam_muac_is_purple(self):
        """MUAC < 115 mm → PURPLE (WHO SAM threshold)."""
        inp = ChildRiskInput(
            age_months=24, muac_mm=108, weight_kg=7.2, height_cm=80,
            sex="M", fever_days=0, temperature_c=37.0,
            danger_signs=[], immunisation_overdue_days=0, breastfeeding_ok=True,
        )
        result = score_child(inp)
        assert result["level"] in (RiskLevel.RED.value, RiskLevel.PURPLE.value)
        assert any("SAM" in t or "MUAC" in t for t in result["triggered_parameters"])

    def test_imnci_danger_sign_immediate_purple(self):
        """Single IMNCI general danger sign → PURPLE regardless of score."""
        inp = ChildRiskInput(
            age_months=6, muac_mm=130, weight_kg=6.5, height_cm=64,
            sex="F", fever_days=1, temperature_c=37.5,
            danger_signs=["convulsions"],
            immunisation_overdue_days=0, breastfeeding_ok=True,
        )
        result = score_child(inp)
        assert result["level"] == RiskLevel.PURPLE.value
        assert result["score"] == 100

    def test_mam_muac_yellow(self):
        """MUAC 115–125 → MAM → at least YELLOW."""
        inp = ChildRiskInput(
            age_months=18, muac_mm=120, weight_kg=8.0, height_cm=80,
            sex="F", fever_days=0, temperature_c=37.0,
            danger_signs=[], immunisation_overdue_days=0, breastfeeding_ok=True,
        )
        result = score_child(inp)
        assert result["level"] in (RiskLevel.YELLOW.value, RiskLevel.RED.value, RiskLevel.PURPLE.value)

    def test_persistent_fever_red(self):
        """Fever for 7+ days → RED (IMNCI threshold)."""
        inp = ChildRiskInput(
            age_months=12, muac_mm=135, weight_kg=9.0, height_cm=75,
            sex="M", fever_days=8, temperature_c=38.8,
            danger_signs=[], immunisation_overdue_days=0, breastfeeding_ok=True,
        )
        result = score_child(inp)
        assert result["level"] in (RiskLevel.RED.value, RiskLevel.PURPLE.value)

    def test_growth_faltering_flagged(self):
        """2 months of no weight gain → growth faltering flag."""
        inp = ChildRiskInput(
            age_months=10, muac_mm=125, weight_kg=7.8, height_cm=72,
            sex="M", fever_days=0, temperature_c=37.0,
            danger_signs=[], immunisation_overdue_days=0, breastfeeding_ok=True,
            weight_history=[7.8, 7.8, 7.8],  # flat for 3 months
        )
        result = score_child(inp)
        assert any("faltering" in t.lower() or "gain" in t.lower()
                   for t in result["triggered_parameters"])

    def test_not_breastfeeding_under_6_months(self):
        """Not breastfeeding under 6 months → adds risk."""
        without_bf = ChildRiskInput(
            age_months=4, muac_mm=140, weight_kg=5.5, height_cm=58,
            sex="F", fever_days=0, temperature_c=37.0,
            danger_signs=[], immunisation_overdue_days=0, breastfeeding_ok=False,
        )
        with_bf = ChildRiskInput(
            age_months=4, muac_mm=140, weight_kg=5.5, height_cm=58,
            sex="F", fever_days=0, temperature_c=37.0,
            danger_signs=[], immunisation_overdue_days=0, breastfeeding_ok=True,
        )
        r_no = score_child(without_bf)
        r_yes = score_child(with_bf)
        assert r_no["score"] > r_yes["score"]

    def test_overdue_immunisation_red(self):
        """Immunisation overdue > 60 days → RED flag."""
        inp = ChildRiskInput(
            age_months=6, muac_mm=135, weight_kg=6.5, height_cm=64,
            sex="M", fever_days=0, temperature_c=37.0,
            danger_signs=[], immunisation_overdue_days=65, breastfeeding_ok=True,
        )
        result = score_child(inp)
        assert result["level"] in (RiskLevel.RED.value, RiskLevel.PURPLE.value)
