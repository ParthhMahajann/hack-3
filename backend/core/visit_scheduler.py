"""
Overdue Visit Scheduler — WHO ANC contact schedule implementation.

WHO ANC 2016 recommends 8 contacts (minimum 4 in T2/T3, roughly every 4 weeks).
NHM child visit schedule: monthly under 1 year, quarterly 1-5 years.

References:
  WHO ANC 2016 (WHO/RHR/16.12)
  MOHFW NHM Home Visit Guidelines 2013
"""
from __future__ import annotations
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Patient, Visit

MATERNAL_INTERVAL_DAYS = 28
CHILD_UNDER1_INTERVAL_DAYS = 30
CHILD_OVER1_INTERVAL_DAYS = 90
OVERDUE_GRACE_DAYS = 3


async def get_overdue_visits(asha_id: str, db: AsyncSession) -> list[dict]:
    """Return patients overdue for a visit, sorted by most overdue first."""
    today = date.today()
    patients_result = await db.execute(select(Patient).where(Patient.asha_id == asha_id))
    patients = patients_result.scalars().all()

    overdue = []
    for patient in patients:
        last_visit_result = await db.execute(
            select(Visit)
            .where(Visit.patient_id == patient.id)
            .order_by(Visit.visit_date.desc())
            .limit(1)
        )
        last_visit = last_visit_result.scalar_one_or_none()

        last_visit_date: date | None = None
        if last_visit:
            try:
                last_visit_date = date.fromisoformat(str(last_visit.visit_date)[:10])
            except (ValueError, AttributeError):
                pass

        interval, visit_type = _get_schedule(patient, today)
        if interval is None:
            continue

        if last_visit_date:
            days_overdue = (today - last_visit_date).days - interval
        else:
            try:
                reg_date = date.fromisoformat(str(patient.created_at)[:10])
                days_overdue = (today - reg_date).days - interval
            except Exception:
                days_overdue = 0

        if days_overdue > OVERDUE_GRACE_DAYS:
            overdue.append({
                "patient_id": patient.id,
                "patient_name": patient.name,
                "patient_type": patient.patient_type,
                "risk_level": patient.current_risk_level or "green",
                "risk_score": patient.current_risk_score or 0,
                "last_visit_date": str(last_visit_date) if last_visit_date else None,
                "days_overdue": days_overdue,
                "recommended_visit_type": visit_type,
                "phone": patient.phone,
            })

    overdue.sort(key=lambda x: x["days_overdue"], reverse=True)
    return overdue


def _get_schedule(patient: Patient, today: date) -> tuple[int | None, str]:
    if patient.patient_type == "maternal":
        if patient.edd:
            try:
                edd = date.fromisoformat(str(patient.edd)[:10])
                if edd < today - timedelta(days=42):
                    return None, ""
            except (ValueError, AttributeError):
                pass
        return MATERNAL_INTERVAL_DAYS, "anc"
    else:
        birth_date_str = patient.birth_date or patient.dob
        if birth_date_str:
            try:
                bd = date.fromisoformat(str(birth_date_str)[:10])
                age_days = (today - bd).days
                if age_days < 0 or age_days > 365 * 5:
                    return None, ""
                interval = CHILD_UNDER1_INTERVAL_DAYS if age_days < 365 else CHILD_OVER1_INTERVAL_DAYS
                return interval, "home_visit"
            except (ValueError, AttributeError):
                pass
        return CHILD_UNDER1_INTERVAL_DAYS, "home_visit"
