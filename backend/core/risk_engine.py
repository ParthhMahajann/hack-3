"""
ASHA Saheli Risk Scoring Engine
================================
All thresholds are derived from published clinical guidelines.
Citations are inline above each constant.

References:
  [1] WHO ANC 2016: "WHO recommendations on antenatal care for a
      positive pregnancy experience", WHO/RHR/16.12
  [2] MOHFW India: "IMNCI Adaptation India", 2009, Chapter 2–4
  [3] WHO MUAC: "Pocket book of hospital care for children", 2013
  [4] WHO Growth Standards: "WHO Child Growth Standards", 2006
  [5] FOGSI: "High-risk pregnancy guidelines", 2020
  [6] IDF/WHO: Gestational diabetes mellitus, FBS threshold
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import numpy as np


# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    GREEN  = "green"    # Routine follow-up
    YELLOW = "yellow"   # ASHA monitors; inform ANM at next meeting
    RED    = "red"      # Push notification to ANM within 1 hour
    PURPLE = "purple"   # Immediate SMS + push to Block Health Officer


RISK_ACTIONS = {
    RiskLevel.GREEN:  "Routine follow-up. Next visit as scheduled.",
    RiskLevel.YELLOW: "Increased monitoring. Inform ANM at next weekly meeting.",
    RiskLevel.RED:    "Urgent: Alert ANM immediately. Consider facility referral.",
    RiskLevel.PURPLE: "EMERGENCY: Refer to PHC/CHC NOW. Block Officer notified.",
}


# ---------------------------------------------------------------------------
# Maternal thresholds  [Ref 1, 5, 6]
# ---------------------------------------------------------------------------

# [Ref 1] WHO ANC 2016, Recommendation 38 — anaemia in pregnancy
HB_SEVERE       = 7.0   # g/dL  → SAM-equivalent maternal risk
HB_MODERATE     = 10.0  # g/dL  → moderate anaemia

# [Ref 1] WHO ANC 2016, Recommendation 29 — hypertension in pregnancy
BP_SEVERE_SYS   = 160   # mmHg  → severe hypertension, imminent eclampsia
BP_SEVERE_DIA   = 110   # mmHg
BP_PREEC_SYS    = 140   # mmHg  → pre-eclampsia threshold
BP_PREEC_DIA    = 90    # mmHg

# [Ref 5] FOGSI 2020 — high-risk age categories
AGE_ADOLESCENT  = 18    # years
AGE_ELDERLY_G   = 35    # years

# [Ref 6] IDF/WHO — gestational diabetes mellitus
GDM_FBS         = 126   # mg/dL  fasting blood sugar

# [Ref 1] WHO ANC 2016 — undernutrition
BMI_UNDERWEIGHT = 18.5  # kg/m²

# ANC contact schedule: 8 contacts recommended [Ref 1, Table 2]
ANC_CONTACTS_REQUIRED = 8
MISSED_ANC_YELLOW = 1
MISSED_ANC_RED    = 2

# Trend sensitivity: slope (mmHg/visit) that triggers escalation
BP_TREND_URGENT  = 4.0  # >4 mmHg/visit rise → escalate one tier
BP_TREND_WATCH   = 2.0  # 2–4 mmHg/visit rise → watch


# ---------------------------------------------------------------------------
# Child/Neonatal thresholds
# ---------------------------------------------------------------------------

# [Ref 3] WHO MUAC pocket book 2013 — acute malnutrition
MUAC_SAM_MM     = 115   # mm  → Severe Acute Malnutrition
MUAC_MAM_MM     = 125   # mm  → Moderate Acute Malnutrition

# [Ref 4] WHO Growth Standards 2006 — underweight Z-scores
WAZ_SEVERE      = -3.0  # SD  → severe underweight
WAZ_MODERATE    = -2.0  # SD  → moderate underweight

# [Ref 2] IMNCI India 2009, Chapter 2 — General Danger Signs
# Any ONE sign present → PURPLE immediately, refer without delay
IMNCI_DANGER_SIGNS = {
    "not_able_to_drink",
    "vomits_everything",
    "convulsions",
    "lethargic_unconscious",
    "severe_chest_indrawing",
    "stridor_calm",
}

# [Ref 2] IMNCI — Fever thresholds
FEVER_DANGER_DAYS = 7   # days: persistent fever → RED
FEVER_TEMP_HIGH   = 38.5  # °C  → significant fever in child

# Immunisation overdue threshold (NVHCP schedule)
IMMUN_OVERDUE_DAYS = 28   # days past due → flag
IMMUNIZATION_URGENT_DAYS = 60  # >2 months overdue = RED flag


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MaternalRiskInput:
    hemoglobin: float           # g/dL
    systolic_bp: int            # mmHg
    diastolic_bp: int           # mmHg
    age: int                    # years
    gestational_week: int       # weeks
    missed_anc_visits: int      # count of missed contacts
    previous_complications: bool  # stillbirth, caesarean, pre-eclampsia
    edema_generalised: bool
    proteinuria_2plus: bool     # ≥2+ on urine dipstick
    fbs: float = 0.0            # mg/dL, 0 = not tested
    bmi_booking: float = 22.0   # kg/m²
    bp_history: list[int] = field(default_factory=list)  # recent systolic readings


@dataclass
class ChildRiskInput:
    age_months: int
    muac_mm: float              # mid-upper arm circumference in mm
    weight_kg: float
    height_cm: float
    sex: str                    # "M" or "F"
    fever_days: int             # 0 = no fever
    temperature_c: float        # °C, 0 = not measured
    danger_signs: list[str]     # from IMNCI_DANGER_SIGNS
    immunisation_overdue_days: int  # 0 = up to date
    breastfeeding_ok: bool      # False = not breastfeeding (< 6 months)
    weight_history: list[float] = field(default_factory=list)  # kg, recent


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _linear_slope(values: list[float]) -> float:
    """Least-squares slope — rising vitals signal deterioration."""
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    coeffs = np.polyfit(x, y, 1)
    return float(coeffs[0])


def _classify(score: int) -> RiskLevel:
    if score >= 80:
        return RiskLevel.PURPLE
    if score >= 60:
        return RiskLevel.RED
    if score >= 30:
        return RiskLevel.YELLOW
    return RiskLevel.GREEN


def _build_result(
    score: int,
    level: RiskLevel,
    triggered: list[str],
    recommended_action: Optional[str] = None,
) -> dict:
    return {
        "score": score,
        "level": level.value,
        "action": recommended_action or RISK_ACTIONS[level],
        "triggered_parameters": triggered,
        "requires_immediate_alert": level in (RiskLevel.RED, RiskLevel.PURPLE),
        "notify_block_officer": level == RiskLevel.PURPLE,
    }


# ---------------------------------------------------------------------------
# Maternal Risk Scoring
# ---------------------------------------------------------------------------

def score_maternal(data: MaternalRiskInput) -> dict:
    """
    Weighted multi-parameter maternal risk score.
    Score 0–100+; classified into GREEN/YELLOW/RED/PURPLE.
    Trend escalation applied on top of threshold scoring.
    """
    score = 0
    triggered: list[str] = []

    # --- Haemoglobin [Ref 1, Rec 38] ---
    # Severe anaemia (<7 g/dL) is a standalone obstetric emergency → RED
    if data.hemoglobin < HB_SEVERE:
        score += 60
        triggered.append(f"Severe anaemia: Hb={data.hemoglobin} g/dL (<{HB_SEVERE})")
    elif data.hemoglobin < HB_MODERATE:
        score += 20
        triggered.append(f"Moderate anaemia: Hb={data.hemoglobin} g/dL (<{HB_MODERATE})")

    # --- Blood pressure [Ref 1, Rec 29] ---
    # Severe hypertension (≥160/110) = severe pre-eclampsia feature → PURPLE directly
    if data.systolic_bp >= BP_SEVERE_SYS or data.diastolic_bp >= BP_SEVERE_DIA:
        score += 80
        triggered.append(
            f"Severe hypertension: {data.systolic_bp}/{data.diastolic_bp} mmHg"
        )
    elif data.systolic_bp >= BP_PREEC_SYS or data.diastolic_bp >= BP_PREEC_DIA:
        score += 35
        triggered.append(
            f"Pre-eclampsia range BP: {data.systolic_bp}/{data.diastolic_bp} mmHg"
        )

    # --- Pre-eclampsia confirmation signs ---
    if data.edema_generalised:
        score += 15
        triggered.append("Generalised oedema")
    if data.proteinuria_2plus:
        score += 20
        triggered.append("Proteinuria ≥2+")

    # --- Pre-eclampsia triad synergy override [Ref 1] ---
    # BP≥140 + proteinuria + oedema = classical pre-eclampsia triad → force PURPLE
    if (
        (data.systolic_bp >= BP_PREEC_SYS or data.diastolic_bp >= BP_PREEC_DIA)
        and data.edema_generalised
        and data.proteinuria_2plus
    ):
        score = max(score, 80)
        triggered.append("Pre-eclampsia triad: BP + oedema + proteinuria")

    # --- Age [Ref 5] ---
    if data.age < AGE_ADOLESCENT:
        score += 10
        triggered.append(f"Adolescent pregnancy: age={data.age}")
    elif data.age > AGE_ELDERLY_G:
        score += 10
        triggered.append(f"Advanced maternal age: age={data.age}")

    # --- Gestational diabetes [Ref 6] ---
    if data.fbs > GDM_FBS:
        score += 15
        triggered.append(f"GDM: FBS={data.fbs} mg/dL (>{GDM_FBS})")

    # --- Obstetric history [Ref 5] ---
    if data.previous_complications:
        score += 15
        triggered.append("Previous obstetric complications")

    # --- ANC adherence [Ref 1, Table 2] ---
    if data.missed_anc_visits >= MISSED_ANC_RED:
        score += 10
        triggered.append(f"Missed ANC contacts: {data.missed_anc_visits}")
    elif data.missed_anc_visits >= MISSED_ANC_YELLOW:
        score += 5
        triggered.append(f"Missed 1 ANC contact")

    # --- Undernutrition ---
    if data.bmi_booking < BMI_UNDERWEIGHT:
        score += 10
        triggered.append(f"Underweight at booking: BMI={data.bmi_booking}")

    # --- Trend escalation: rising BP even before threshold ---
    if len(data.bp_history) >= 3:
        slope = _linear_slope(data.bp_history)
        if slope >= BP_TREND_URGENT:
            score += 20
            triggered.append(
                f"Rapidly rising BP trend: +{slope:.1f} mmHg/visit"
            )
        elif slope >= BP_TREND_WATCH:
            score += 10
            triggered.append(f"Rising BP trend: +{slope:.1f} mmHg/visit")

    level = _classify(score)
    return _build_result(score, level, triggered)


# ---------------------------------------------------------------------------
# Child Risk Scoring
# ---------------------------------------------------------------------------

def score_child(data: ChildRiskInput) -> dict:
    """
    IMNCI + WHO growth standard child risk scoring.
    Any general danger sign → PURPLE immediately.
    """
    score = 0
    triggered: list[str] = []

    # --- IMNCI General Danger Signs [Ref 2, Ch 2] ---
    # Any single sign = immediate referral
    present_danger = [s for s in data.danger_signs if s in IMNCI_DANGER_SIGNS]
    if present_danger:
        triggered.append(f"IMNCI danger sign(s): {', '.join(present_danger)}")
        return _build_result(100, RiskLevel.PURPLE, triggered,
                             "EMERGENCY: IMNCI general danger sign. Refer to hospital NOW.")

    # --- MUAC [Ref 3] ---
    if data.muac_mm > 0:
        if data.muac_mm < MUAC_SAM_MM:
            score += 40
            triggered.append(f"SAM: MUAC={data.muac_mm}mm (<{MUAC_SAM_MM}mm)")
        elif data.muac_mm < MUAC_MAM_MM:
            score += 20
            triggered.append(f"MAM: MUAC={data.muac_mm}mm (<{MUAC_MAM_MM}mm)")

    # --- Weight-for-age Z-score [Ref 4] ---
    if data.weight_kg > 0 and data.age_months > 0:
        waz = _compute_waz(data.weight_kg, data.age_months, data.sex)
        if waz is not None:
            if waz <= WAZ_SEVERE:
                score += 30
                triggered.append(f"Severe underweight: WAZ={waz:.2f}")
            elif waz <= WAZ_MODERATE:
                score += 15
                triggered.append(f"Moderate underweight: WAZ={waz:.2f}")

    # --- Growth faltering: 2 consecutive months no gain ---
    if len(data.weight_history) >= 3:
        gains = [
            data.weight_history[i] - data.weight_history[i - 1]
            for i in range(1, len(data.weight_history))
        ]
        if all(g <= 0 for g in gains[-2:]):
            score += 20
            triggered.append("Growth faltering: no weight gain for ≥2 months")

    # --- Fever [Ref 2, Ch 3] ---
    # Persistent fever ≥7 days = IMNCI referral criterion → RED minimum
    if data.fever_days >= FEVER_DANGER_DAYS:
        score += 60
        triggered.append(f"Persistent fever: {data.fever_days} days (IMNCI referral)")
    elif data.temperature_c >= FEVER_TEMP_HIGH:
        score += 10
        triggered.append(f"Fever: {data.temperature_c}°C")

    # --- Breastfeeding (under 6 months) ---
    if data.age_months < 6 and not data.breastfeeding_ok:
        score += 15
        triggered.append("Not exclusively breastfeeding (<6 months)")

    # --- Immunisation overdue ---
    # >60 days overdue = significant public health risk → RED
    if data.immunisation_overdue_days >= IMMUNIZATION_URGENT_DAYS:
        score += 60
        triggered.append(
            f"Immunisation severely overdue: {data.immunisation_overdue_days} days"
        )
    elif data.immunisation_overdue_days >= IMMUN_OVERDUE_DAYS:
        score += 15
        triggered.append(f"Immunisation overdue: {data.immunisation_overdue_days} days")

    level = _classify(score)
    return _build_result(score, level, triggered)


# ---------------------------------------------------------------------------
# Household composite risk
# ---------------------------------------------------------------------------

def score_household(maternal_result: Optional[dict], child_results: list[dict]) -> dict:
    """
    Highest individual risk within a household = household risk.
    Used in Block Officer heatmap.
    """
    all_results = []
    if maternal_result:
        all_results.append(maternal_result)
    all_results.extend(child_results)

    if not all_results:
        return _build_result(0, RiskLevel.GREEN, [])

    level_order = {
        RiskLevel.PURPLE.value: 3,
        RiskLevel.RED.value: 2,
        RiskLevel.YELLOW.value: 1,
        RiskLevel.GREEN.value: 0,
    }
    worst = max(all_results, key=lambda r: level_order.get(r["level"], 0))
    return worst


# ---------------------------------------------------------------------------
# WHO Weight-for-Age Z-score (simplified LMS method)
# Ref [4]: WHO Child Growth Standards, 2006, Table 1 (0–60 months)
# ---------------------------------------------------------------------------

# Abbreviated LMS coefficients for weight-for-age, boys and girls
# Format: age_months -> (L, M, S)
# Source: WHO Multicentre Growth Reference Study Group (2006)
_WAZ_LMS_BOYS: dict[int, tuple[float, float, float]] = {
    0:  (0.3487, 3.3464, 0.14602),
    1:  (0.2297, 4.4709, 0.13395),
    3:  (0.2986, 6.3762, 0.12385),
    6:  (0.1722, 7.9340, 0.11687),
    9:  (0.2984, 9.1797, 0.11528),
    12: (0.2761, 9.6479, 0.11648),
    18: (0.1233, 10.9350, 0.11437),
    24: (0.0317, 12.1391, 0.11619),
    36: (-0.2986, 14.2760, 0.12238),
    48: (-0.5664, 16.2993, 0.12612),
    60: (-0.7644, 18.3418, 0.13032),
}
_WAZ_LMS_GIRLS: dict[int, tuple[float, float, float]] = {
    0:  (0.3809, 3.2322, 0.14171),
    1:  (0.1714, 4.1873, 0.13724),
    3:  (0.2986, 5.7420, 0.12737),
    6:  (0.2376, 7.2972, 0.11914),
    9:  (0.2579, 8.4822, 0.11830),
    12: (0.2092, 8.9481, 0.12007),
    18: (0.0976, 10.2052, 0.11815),
    24: (-0.0199, 11.5022, 0.12099),
    36: (-0.3143, 13.9287, 0.12614),
    48: (-0.6165, 15.9689, 0.13195),
    60: (-0.8557, 18.2982, 0.13729),
}

def _nearest_age_key(age_months: int, lms_table: dict) -> int:
    keys = sorted(lms_table.keys())
    return min(keys, key=lambda k: abs(k - age_months))


def _compute_waz(weight_kg: float, age_months: int, sex: str) -> Optional[float]:
    """
    WHO LMS method: Z = ((X/M)^L - 1) / (L*S)
    Returns None if age out of range or data missing.
    """
    if age_months < 0 or age_months > 60:
        return None
    table = _WAZ_LMS_BOYS if sex.upper() == "M" else _WAZ_LMS_GIRLS
    key = _nearest_age_key(age_months, table)
    L, M, S = table[key]
    if L == 0:
        return float(np.log(weight_kg / M) / S)
    return float(((weight_kg / M) ** L - 1) / (L * S))
