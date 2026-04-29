import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Visit, Patient, RiskAlert, IncentiveEvent, User
from backend.schemas import VisitCreate, VisitOut
from backend.routers.auth import get_current_user
from backend.core.risk_engine import (
    MaternalRiskInput, ChildRiskInput,
    score_maternal, score_child, _compute_waz
)
from backend.core.alert_service import dispatch_risk_alert
from backend.core.incentive_calculator import calculate_incentives_from_visit
from backend.core.ml_risk_predictor import (
    MaternalMLInput, ChildMLInput,
    predict_maternal_risk, predict_child_risk
)
from backend.core.nlp_summarizer import summarise_visit

router = APIRouter(prefix="/visits", tags=["visits"])


def _compute_risk(patient: Patient, vitals: dict, observations: dict) -> dict:
    """
    Route to correct scorer based on patient type.
    Returns rule-based score + ML 30-day forecast probability.
    """
    from backend.core.risk_engine import _linear_slope
    if patient.patient_type == "maternal":
        bp_history = observations.get("bp_history", [])
        inp = MaternalRiskInput(
            hemoglobin=vitals.get("hemoglobin", 12.0),
            systolic_bp=vitals.get("systolic_bp", 110),
            diastolic_bp=vitals.get("diastolic_bp", 70),
            age=patient.age or 25,
            gestational_week=vitals.get("gestational_week", 20),
            missed_anc_visits=observations.get("missed_anc_visits", 0),
            previous_complications=observations.get("previous_complications", False),
            edema_generalised=observations.get("edema_generalised", False),
            proteinuria_2plus=observations.get("proteinuria_2plus", False),
            fbs=vitals.get("fbs", 0.0),
            bmi_booking=vitals.get("bmi_booking", 22.0),
            bp_history=bp_history,
        )
        result = score_maternal(inp)
        # Add ML forecast
        ml = predict_maternal_risk(MaternalMLInput(
            hemoglobin=vitals.get("hemoglobin", 12.0),
            systolic_bp=vitals.get("systolic_bp", 110),
            diastolic_bp=vitals.get("diastolic_bp", 70),
            gestational_week=vitals.get("gestational_week", 20),
            age=patient.age or 25,
            missed_anc_visits=observations.get("missed_anc_visits", 0),
            bp_slope=_linear_slope(bp_history) if len(bp_history) >= 2 else 0.0,
            bmi_booking=vitals.get("bmi_booking", 22.0),
            fbs=vitals.get("fbs", 0.0),
            edema=observations.get("edema_generalised", False),
            proteinuria=observations.get("proteinuria_2plus", False),
            prev_complications=observations.get("previous_complications", False),
        ))
        result["ml_forecast"] = ml
        return result
    else:
        age_months = _age_in_months(patient.birth_date)
        inp = ChildRiskInput(
            age_months=age_months,
            muac_mm=vitals.get("muac_mm", 0),
            weight_kg=vitals.get("weight_kg", 0),
            height_cm=vitals.get("height_cm", 0),
            sex=patient.sex or "M",
            fever_days=observations.get("fever_days", 0),
            temperature_c=vitals.get("temperature_c", 0),
            danger_signs=observations.get("danger_signs", []),
            immunisation_overdue_days=observations.get("immunisation_overdue_days", 0),
            breastfeeding_ok=observations.get("breastfeeding_ok", True),
            weight_history=observations.get("weight_history", []),
        )
        result = score_child(inp)
        waz = _compute_waz(vitals.get("weight_kg", 8.0), age_months, patient.sex or "M") or -1.0
        ml = predict_child_risk(ChildMLInput(
            muac_mm=vitals.get("muac_mm", 130),
            waz_score=waz,
            age_months=age_months,
            fever_days=observations.get("fever_days", 0),
            immunisation_overdue_days=observations.get("immunisation_overdue_days", 0),
            breastfeeding_ok=observations.get("breastfeeding_ok", True),
        ))
        result["ml_forecast"] = ml
        return result


def _age_in_months(birth_date: str | None) -> int:
    if not birth_date:
        return 12
    try:
        bd = datetime.strptime(birth_date, "%Y-%m-%d")
        delta = datetime.now() - bd
        return max(0, delta.days // 30)
    except Exception:
        return 12


@router.post("/", response_model=VisitOut, status_code=201)
async def log_visit(
    data: VisitCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Fetch patient
    result = await db.execute(select(Patient).where(Patient.id == data.patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Patient not found")

    # Compute risk score
    risk = _compute_risk(patient, data.vitals, data.observations)

    # Persist visit
    visit = Visit(
        id=data.id,
        patient_id=data.patient_id,
        asha_id=current_user.id,
        visit_type=data.visit_type,
        visit_date=data.visit_date,
        vitals=data.vitals,
        observations=data.observations,
        risk_level=risk["level"],
        risk_score=risk["score"],
        risk_triggered=risk["triggered_parameters"],
        gps_lat=data.gps_lat,
        gps_lng=data.gps_lng,
        synced_at=datetime.now(timezone.utc),
        device_id=data.device_id,
        updated_at=datetime.fromtimestamp(data.updated_at, tz=timezone.utc)
        if data.updated_at else datetime.now(timezone.utc),
    )
    db.add(visit)

    # Update patient's current risk (denormalised for dashboard speed)
    patient.current_risk_level = risk["level"]
    patient.current_risk_score = risk["score"]

    # Dispatch alert for RED/PURPLE
    if risk["requires_immediate_alert"]:
        alert_result = await dispatch_risk_alert(
            patient_name=patient.name,
            patient_id=patient.id,
            risk_result=risk,
            asha_name=current_user.name,
            area=current_user.area_name or "",
        )
        alert = RiskAlert(
            patient_id=patient.id,
            visit_id=data.id,
            risk_level=risk["level"],
            risk_score=risk["score"],
            triggered_params=risk["triggered_parameters"],
            channels_used=alert_result.get("channels", []),
        )
        db.add(alert)

    # Calculate and persist incentive events
    # Merge visit_date into observations so the calculator can stamp event_date
    obs_with_date = {**data.observations, "visit_date": data.visit_date}
    incentive_events = calculate_incentives_from_visit(
        visit_type=data.visit_type,
        observations=obs_with_date,
        patient={"id": patient.id, "name": patient.name},
    )
    for ev in incentive_events:
        db.add(IncentiveEvent(
            asha_id=current_user.id,
            patient_id=ev.patient_id,
            patient_name=ev.patient_name,
            event_type=ev.type.value,
            amount=ev.amount,
            event_date=ev.event_date,
            notes=ev.notes,
        ))

    await db.commit()
    await db.refresh(visit)
    out = VisitOut.model_validate(visit)
    out.ml_forecast = risk.get("ml_forecast")
    # NLP summary (bilingual)
    nlp = summarise_visit(
        patient_type=patient.patient_type,
        vitals=data.vitals, observations=data.observations,
        risk_level=risk["level"], risk_score=risk["score"],
        triggered=risk["triggered_parameters"],
        ml_forecast=risk.get("ml_forecast"),
    )
    out.ml_forecast = {**(risk.get("ml_forecast") or {}), "nlp_summary": nlp}
    return out


@router.get("/overdue")
async def overdue_visits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Patients overdue for a visit per WHO ANC/NHM schedule."""
    from backend.core.visit_scheduler import get_overdue_visits
    return await get_overdue_visits(current_user.id, db)


@router.get("/patient/{patient_id}", response_model=list[VisitOut])
async def get_patient_visits(
    patient_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Visit)
        .where(Visit.patient_id == patient_id)
        .order_by(Visit.visit_date.desc())
    )
    return result.scalars().all()
