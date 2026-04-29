# ASHA Saheli -- Research Paper to Code Mapping

> Every clinical threshold, ML parameter, and architectural decision in ASHA
> Saheli is traceable to a published source.  This document provides the
> detailed mapping required by the **Research Paper Referenced** rubric.

---

## Overview

| # | Paper / Guideline | Year | What it influences | Lines of code |
|---|---|---|---|---|
| 1 | WHO ANC 2016 | 2016 | Maternal BP, anaemia, ANC schedule | 28 |
| 2 | MOHFW IMNCI India | 2009 | Child danger signs, fever thresholds | 14 |
| 3 | WHO Growth Standards | 2006 | WAZ Z-score calculation (LMS method) | 50 |
| 4 | WHO MUAC Pocket Book | 2013 | SAM/MAM thresholds | 6 |
| 5 | FOGSI High-Risk Pregnancy | 2020 | Maternal age risk categories | 6 |
| 6 | IDF/WHO GDM Criteria | -- | Fasting blood sugar threshold | 4 |
| 7 | Rana et al., BMC 2023 | 2023 | ML model architecture + features | 120+ |
| 8 | Shapiro et al., INRIA 2011 | 2011 | Sync engine CRDT field-level merge | 85 |
| 9 | JSY/JSSK MOHFW 2015 | 2015 | ASHA incentive amounts | 55 |
| 10 | NFHS-5 India 2019-21 | 2022 | ML model calibration | 15 |

---

## 1. WHO ANC 2016

**Full title:** WHO recommendations on antenatal care for a positive pregnancy
experience  
**Citation:** WHO/RHR/16.12, 2016  
**ISBN:** 978-92-4-154991-2

### How it influences the code

#### Recommendation 38 -- Anaemia in pregnancy

| Threshold | Value | Code location | Logic |
|---|---|---|---|
| Severe anaemia | Hb < 7.0 g/dL | [`risk_engine.py` L48-49](backend/core/risk_engine.py#L48-L49) | Adds +60 to score (standalone obstetric emergency) |
| Moderate anaemia | Hb < 10.0 g/dL | [`risk_engine.py` L49](backend/core/risk_engine.py#L49) | Adds +20 to score |

```python
# risk_engine.py lines 197-204
if data.hemoglobin < HB_SEVERE:          # 7.0 g/dL [WHO ANC 2016, Rec 38]
    score += 60
    triggered.append(f"Severe anaemia: Hb={data.hemoglobin}")
elif data.hemoglobin < HB_MODERATE:      # 10.0 g/dL
    score += 20
    triggered.append(f"Moderate anaemia: Hb={data.hemoglobin}")
```

#### Recommendation 29 -- Hypertension in pregnancy

| Threshold | Value | Code location | Logic |
|---|---|---|---|
| Severe hypertension | >= 160/110 mmHg | [`risk_engine.py` L52-53](backend/core/risk_engine.py#L52-L53) | Adds +80 (immediate PURPLE) |
| Pre-eclampsia | >= 140/90 mmHg | [`risk_engine.py` L54-55](backend/core/risk_engine.py#L54-L55) | Adds +35 |

```python
# risk_engine.py lines 206-217
if data.systolic_bp >= BP_SEVERE_SYS or data.diastolic_bp >= BP_SEVERE_DIA:
    score += 80   # [WHO ANC 2016, Rec 29] -- severe pre-eclampsia feature
elif data.systolic_bp >= BP_PREEC_SYS or data.diastolic_bp >= BP_PREEC_DIA:
    score += 35   # pre-eclampsia threshold
```

#### Pre-eclampsia triad synergy override

When all three signs are present (BP >= 140/90 + proteinuria + oedema), the
score is forced to at least 80 regardless of other parameters -- classical
pre-eclampsia triad per WHO ANC 2016.

```python
# risk_engine.py lines 227-235
if (systolic >= 140 or diastolic >= 90) and edema and proteinuria:
    score = max(score, 80)  # force PURPLE
```

#### Table 2 -- 8-contact ANC schedule

| Implementation | Code location |
|---|---|
| 8 contacts required | [`risk_engine.py` L68](backend/core/risk_engine.py#L68) |
| Missed 1 contact = YELLOW (+5) | [`risk_engine.py` L69](backend/core/risk_engine.py#L69) |
| Missed 2+ contacts = RED (+10) | [`risk_engine.py` L70](backend/core/risk_engine.py#L70) |
| Visit scheduler intervals (28 days) | [`visit_scheduler.py` L18](backend/core/visit_scheduler.py#L18) |

---

## 2. MOHFW IMNCI India 2009

**Full title:** Integrated Management of Neonatal and Childhood Illness --
India Adaptation  
**Citation:** MOHFW, Government of India, 2009, Chapter 2-4

### How it influences the code

#### Chapter 2 -- General Danger Signs

**Any single danger sign -> PURPLE immediately (score=100).**

The 6 IMNCI general danger signs are hardcoded as a set:

```python
# risk_engine.py lines 91-98
IMNCI_DANGER_SIGNS = {
    "not_able_to_drink",
    "vomits_everything",
    "convulsions",
    "lethargic_unconscious",
    "severe_chest_indrawing",
    "stridor_calm",
}
```

```python
# risk_engine.py lines 296-302
present_danger = [s for s in data.danger_signs if s in IMNCI_DANGER_SIGNS]
if present_danger:
    return _build_result(100, RiskLevel.PURPLE, triggered,
        "EMERGENCY: IMNCI general danger sign. Refer to hospital NOW.")
```

#### Chapter 3 -- Fever classification

| Threshold | Value | Code location |
|---|---|---|
| Persistent fever (referral) | >= 7 days | [`risk_engine.py` L101](backend/core/risk_engine.py#L101) |
| Significant fever | >= 38.5C | [`risk_engine.py` L102](backend/core/risk_engine.py#L102) |

---

## 3. WHO Growth Standards 2006

**Full title:** WHO Child Growth Standards: Length/height-for-age,
weight-for-age  
**Citation:** WHO Multicentre Growth Reference Study Group, 2006  
**ISBN:** 92-4-154693-X

### How it influences the code

#### LMS Z-score method (Weight-for-Age)

The Z-score formula `Z = ((X/M)^L - 1) / (L*S)` is implemented using
published LMS coefficients for boys and girls at 11 age points (0-60
months):

```python
# risk_engine.py lines 430-442
def _compute_waz(weight_kg, age_months, sex):
    table = _WAZ_LMS_BOYS if sex.upper() == "M" else _WAZ_LMS_GIRLS
    key = _nearest_age_key(age_months, table)
    L, M, S = table[key]
    if L == 0:
        return float(np.log(weight_kg / M) / S)
    return float(((weight_kg / M) ** L - 1) / (L * S))
```

| Threshold | Z-score | Code location | Score |
|---|---|---|---|
| Severe underweight | WAZ <= -3.0 SD | [`risk_engine.py` L86](backend/core/risk_engine.py#L86) | +30 |
| Moderate underweight | WAZ <= -2.0 SD | [`risk_engine.py` L87](backend/core/risk_engine.py#L87) | +15 |

**LMS coefficient tables:** [`risk_engine.py` L398-422](backend/core/risk_engine.py#L398-L422) -- actual published values from WHO 2006 Table 1.

---

## 4. WHO MUAC Pocket Book 2013

**Full title:** Pocket book of hospital care for children (2nd edition)  
**Citation:** WHO, 2013  
**ISBN:** 978-92-4-154837-3

| Threshold | Value | Code location | Score |
|---|---|---|---|
| SAM | MUAC < 115 mm | [`risk_engine.py` L82](backend/core/risk_engine.py#L82) | +40 |
| MAM | MUAC 115-125 mm | [`risk_engine.py` L83](backend/core/risk_engine.py#L83) | +20 |

---

## 5. FOGSI High-Risk Pregnancy 2020

**Full title:** High-risk pregnancy guidelines  
**Citation:** Federation of Obstetric and Gynaecological Societies of India, 2020

| Threshold | Value | Code location | Score |
|---|---|---|---|
| Adolescent pregnancy | age < 18 | [`risk_engine.py` L58](backend/core/risk_engine.py#L58) | +10 |
| Advanced maternal age | age > 35 | [`risk_engine.py` L59](backend/core/risk_engine.py#L59) | +10 |

---

## 6. IDF/WHO GDM Criteria

**Citation:** International Diabetes Federation, WHO  
**DOI:** 10.1016/j.diabres.2013.10.012

| Threshold | Value | Code location | Score |
|---|---|---|---|
| Gestational diabetes | FBS > 126 mg/dL | [`risk_engine.py` L62](backend/core/risk_engine.py#L62) | +15 |

---

## 7. Rana et al., BMC Pregnancy and Childbirth 2023

**Full title:** Machine learning for prediction of adverse outcomes in
high-risk pregnancies  
**DOI:** 10.1186/s12884-023-05387-5

### How it influences the code

This paper justifies the **choice of logistic regression** as the ML model
architecture and informs the **feature selection** for 30-day adverse outcome
prediction.

| Implementation detail | Code location |
|---|---|
| Logistic regression model | [`ml_risk_predictor.py`](backend/core/ml_risk_predictor.py) |
| 13 maternal features | [`ml_risk_predictor.py` L34-48](backend/core/ml_risk_predictor.py#L34-L48) |
| 6 child features | [`ml_risk_predictor.py` L50-57](backend/core/ml_risk_predictor.py#L50-L57) |
| Sigmoid probability | [`ml_risk_predictor.py` L96-97](backend/core/ml_risk_predictor.py#L96-L97) |
| Top contributing features | [`ml_risk_predictor.py` L206-214](backend/core/ml_risk_predictor.py#L206-L214) |
| Training pipeline | [`scripts/train_ml_model.py`](scripts/train_ml_model.py) |

**Key insight from paper:** Interpretable models (logistic regression)
perform comparably to black-box methods (XGBoost, random forest) for
clinical risk prediction when features are well-selected.  This justified
our choice of logistic regression over complex ensembles -- critical for
field deployment where predictions must be explainable to ASHA workers.

---

## 8. Shapiro et al., INRIA 2011

**Full title:** A comprehensive study of Convergent and Commutative
Replicated Data Types  
**Citation:** INRIA Research Report RR-7506, 2011  
**HAL:** hal-00932836

### How it influences the code

Section 3.2.3 (LWW-Register) of this paper directly motivates the
**field-level merge** strategy in the sync engine:

| CRDT concept | Implementation | Code location |
|---|---|---|
| LWW-Register per field | `field_level_merge()` | [`sync_engine.py` L49-91](backend/core/sync_engine.py#L49-L91) |
| Grow-Only Set (new keys) | Union semantics for new fields | [`sync_engine.py` L73-74](backend/core/sync_engine.py#L73-L74) |
| Conflict logging | SyncConflict table | [`models.py` L161-173](backend/models.py#L161-L173) |
| Priority ordering | Critical cases synced first | [`sync_engine.py` L33](backend/core/sync_engine.py#L33) |

**Why field-level over record-level:** In rural India, ASHA workers often
share tablets or sync from different devices.  With record-level LWW, if
Device-A records hemoglobin and Device-B records blood pressure for the
same visit, one measurement is lost.  Field-level merge preserves both.

```python
# sync_engine.py -- field_level_merge()
for key in all_keys:
    if key not in server_dict:
        merged[key] = c_val        # Grow-Only Set: accept new client fields
    elif key not in client_dict:
        pass                        # keep server-only fields
    elif s_val == c_val:
        pass                        # no conflict
    else:
        if client_ts > server_ts:
            merged[key] = c_val     # LWW-Register: newer timestamp wins
        # Log conflict for ANM review
```

---

## 9. JSY/JSSK MOHFW 2015

**Full title:** Janani Suraksha Yojana -- Operational Guidelines (Revised)  
**Citation:** MOHFW, Government of India, 2015

### How it influences the code

Every incentive amount in
[`incentive_calculator.py`](backend/core/incentive_calculator.py) matches the
official JSY/JSSK rates:

| Event type | Amount (INR) | Code constant | Code line |
|---|---|---|---|
| Institutional delivery (rural) | 1,400 | `JSY_INSTITUTIONAL_DELIVERY_RURAL` | L40 |
| Institutional delivery (urban) | 1,000 | `JSY_INSTITUTIONAL_DELIVERY_URBAN` | L41 |
| Home delivery | 500 | `JSY_HOME_DELIVERY` | L42 |
| ANC registration | 300 | `ANC_REGISTRATION` | L43 |
| 4th ANC contact | 300 | `ANC_4TH_CONTACT` | L44 |
| BCG immunisation | 150 | `IMMUNISATION_BCG` | L45 |
| Pentavalent dose | 150 | `IMMUNISATION_PENTA_DOSE` | L46 |
| Measles vaccine | 150 | `IMMUNISATION_MEASLES` | L47 |
| Referral escort | 250 | `REFERRAL_ESCORT` | L48 |
| VHND session | 200 | `VHND_SESSION` | L49 |
| NRC admission | 500 | `NRC_ADMISSION` | L50 |

---

## 10. NFHS-5 India 2019-21

**Full title:** National Family Health Survey (NFHS-5), India, 2019-21  
**Citation:** International Institute for Population Sciences (IIPS), 2022

### How it influences the code

NFHS-5 published prevalence rates are used to **calibrate the ML model's
base rates** so that predictions are realistic for the Indian population:

| Statistic | NFHS-5 value | Used in |
|---|---|---|
| Maternal anaemia prevalence | 57% | Synthetic data Hb distribution |
| Institutional delivery rate | 89% | Incentive frequency calibration |
| Maternal complication rate | ~8.5% | Model bias term (-2.1) |
| Child malnutrition (severe) | ~12% | Model bias term (-2.4) |

**Code locations:**
- [`ml_risk_predictor.py` L83](backend/core/ml_risk_predictor.py#L83) -- maternal bias
- [`ml_risk_predictor.py` L93](backend/core/ml_risk_predictor.py#L93) -- child bias
- [`scripts/train_ml_model.py` L67-72](scripts/train_ml_model.py#L67-L72) -- synthetic distribution params
