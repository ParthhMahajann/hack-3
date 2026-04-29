"""
NLP Visit Summarizer — Plain-language clinical summaries (EN + Hindi)
References: WHO ANC 2016, MOHFW ASHA Module 6
"""
from __future__ import annotations

_HB_SEVERE, _HB_MODERATE = 7.0, 10.0
_BP_SEVERE_SYS, _BP_SEVERE_DIA = 160, 110
_BP_PREEC_SYS, _BP_PREEC_DIA = 140, 90
_GDM_FBS = 126


def summarise_visit(patient_type, vitals, observations, risk_level, risk_score,
                    triggered=None, ml_forecast=None, lang="both"):
    """
    Generate a plain-language clinical summary.
    lang="en"   → English only
    lang="hi"   → Hindi only
    lang="both" → bilingual (default, used in API responses)
    """
    if patient_type == "maternal":
        result = _maternal(vitals, observations, risk_level, risk_score, ml_forecast)
    else:
        result = _child(vitals, observations, risk_level, risk_score, ml_forecast)

    if lang == "en":
        return {
            "summary": result["summary_en"],
            "key_findings": result["key_findings"],
            "recommendation": result["recommendation_en"],
            "ml_forecast": result.get("ml_forecast_en", ""),
            "urgency": result["urgency"],
        }
    if lang == "hi":
        return {
            "summary": result["summary_hi"],
            "key_findings": result["key_findings_hi"],
            "recommendation": result["recommendation_hi"],
            "urgency": result["urgency"],
        }
    # Default: full bilingual payload
    return result


def _maternal(v, o, level, score, ml):
    en, hi = [], []
    hb = v.get("hemoglobin", 0)
    sys_bp, dia_bp = v.get("systolic_bp", 0), v.get("diastolic_bp", 0)
    fbs, wt = v.get("fbs", 0), v.get("weight_kg", 0)

    if hb > 0:
        if hb < _HB_SEVERE:
            en.append(f"Severe anaemia (Hb {hb} g/dL) — urgent iron/transfusion needed")
            hi.append(f"गंभीर एनीमिया (Hb {hb} g/dL) — तुरंत आयरन/रक्त आधान आवश्यक")
        elif hb < _HB_MODERATE:
            en.append(f"Moderate anaemia (Hb {hb} g/dL) — increase iron supplements")
            hi.append(f"मध्यम एनीमिया (Hb {hb} g/dL) — आयरन की खुराक बढ़ाएं")
        else:
            en.append(f"Haemoglobin normal ({hb} g/dL)")
            hi.append(f"हीमोग्लोबिन सामान्य ({hb} g/dL)")

    if sys_bp > 0:
        if sys_bp >= _BP_SEVERE_SYS or dia_bp >= _BP_SEVERE_DIA:
            en.append(f"Severe hypertension ({sys_bp}/{dia_bp}) — eclampsia risk")
            hi.append(f"गंभीर उच्च रक्तचाप ({sys_bp}/{dia_bp}) — एक्लम्पसिया का खतरा")
        elif sys_bp >= _BP_PREEC_SYS or dia_bp >= _BP_PREEC_DIA:
            en.append(f"Pre-eclampsia range BP ({sys_bp}/{dia_bp})")
            hi.append(f"प्री-एक्लम्पसिया बीपी ({sys_bp}/{dia_bp})")
        else:
            en.append(f"BP normal ({sys_bp}/{dia_bp})")
            hi.append(f"बीपी सामान्य ({sys_bp}/{dia_bp})")

    if o.get("edema_generalised") and o.get("proteinuria_2plus"):
        en.append("Pre-eclampsia triad: oedema + proteinuria")
        hi.append("प्री-एक्लम्पसिया: सूजन + प्रोटीनूरिया")
    if fbs > _GDM_FBS:
        en.append(f"Gestational diabetes (FBS {fbs} mg/dL)")
        hi.append(f"गर्भकालीन मधुमेह (FBS {fbs} mg/dL)")
    missed = o.get("missed_anc_visits", 0)
    if missed >= 2:
        en.append(f"Missed {missed} ANC contacts")
        hi.append(f"{missed} ANC मुलाकातें छूटीं")

    rec_en, rec_hi = _rec(level)
    ml_en = f"30-day adverse outcome probability: {ml['percentage']}%." if ml else ""
    return {"summary_en": ". ".join(en) + f". Risk: {level.upper()} ({score}/100). {rec_en}",
            "summary_hi": "। ".join(hi) + f"। जोखिम: {level.upper()} ({score}/100)। {rec_hi}",
            "key_findings": en, "key_findings_hi": hi,
            "recommendation_en": rec_en, "recommendation_hi": rec_hi,
            "ml_forecast_en": ml_en, "urgency": level}


def _child(v, o, level, score, ml):
    en, hi = [], []
    muac, wt = v.get("muac_mm", 0), v.get("weight_kg", 0)
    fever, danger = o.get("fever_days", 0), o.get("danger_signs", [])

    if danger:
        en.append(f"IMNCI danger sign(s): {', '.join(s.replace('_',' ') for s in danger)} — IMMEDIATE referral")
        hi.append(f"IMNCI खतरे के संकेत — तुरंत रेफर करें")
    if muac > 0:
        if muac < 115:
            en.append(f"SAM (MUAC {muac}mm < 115mm)")
            hi.append(f"गंभीर कुपोषण (MUAC {muac}mm)")
        elif muac < 125:
            en.append(f"MAM (MUAC {muac}mm)")
            hi.append(f"मध्यम कुपोषण (MUAC {muac}mm)")
        else:
            en.append(f"MUAC normal ({muac}mm)")
            hi.append(f"MUAC सामान्य ({muac}mm)")
    if fever >= 7:
        en.append(f"Persistent fever ({fever} days)")
        hi.append(f"लगातार बुखार ({fever} दिन)")
    if not o.get("breastfeeding_ok", True):
        en.append("Not breastfeeding")
        hi.append("स्तनपान नहीं")
    imm = o.get("immunisation_overdue_days", 0)
    if imm >= 60:
        en.append(f"Immunisation overdue ({imm} days)")
        hi.append(f"टीकाकरण विलंबित ({imm} दिन)")

    rec_en, rec_hi = _rec(level)
    ml_en = f"30-day hospitalisation probability: {ml['percentage']}%." if ml else ""
    return {"summary_en": ". ".join(en) + f". Risk: {level.upper()} ({score}/100). {rec_en}",
            "summary_hi": "। ".join(hi) + f"। जोखिम: {level.upper()} ({score}/100)। {rec_hi}",
            "key_findings": en, "key_findings_hi": hi,
            "recommendation_en": rec_en, "recommendation_hi": rec_hi,
            "ml_forecast_en": ml_en, "urgency": level}


def _rec(level):
    return {"green": ("Routine follow-up. Next visit as scheduled.",
                      "नियमित फॉलो-अप। अगली मुलाकात निर्धारित समय पर।"),
            "yellow": ("Increased monitoring. Inform ANM at next meeting.",
                       "निगरानी बढ़ाएं। ANM को सूचित करें।"),
            "red": ("URGENT: Alert ANM immediately. Consider referral.",
                    "तत्काल: ANM को तुरंत सूचित करें। रेफरल पर विचार करें।"),
            "purple": ("EMERGENCY: Refer to PHC/CHC NOW. Block Officer notified.",
                       "आपातकाल: अभी PHC/CHC भेजें। ब्लॉक अधिकारी को सूचित किया गया।"),
            }.get(level, ("Routine follow-up.", "नियमित फॉलो-अप।"))
