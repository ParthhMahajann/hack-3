import csv
import io
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Patient, Visit, RiskAlert, User, IncentiveEvent
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated stats for Block Officer or ASHA dashboard."""
    if current_user.role == "asha":
        patient_q = select(func.count()).where(Patient.asha_id == current_user.id)
        high_risk_q = select(func.count()).where(
            and_(Patient.asha_id == current_user.id,
                 Patient.current_risk_level.in_(["red", "purple"]))
        )
        # Scope alerts to this ASHA's patients only
        alerts_q = (
            select(func.count())
            .join(Patient, RiskAlert.patient_id == Patient.id)
            .where(and_(RiskAlert.acknowledged == False,
                        Patient.asha_id == current_user.id))
        )
        incentive_q = select(func.sum(IncentiveEvent.amount)).where(
            and_(IncentiveEvent.asha_id == current_user.id,
                 IncentiveEvent.verified == False)
        )
    else:
        patient_q = select(func.count(Patient.id))
        high_risk_q = select(func.count()).where(
            Patient.current_risk_level.in_(["red", "purple"])
        )
        alerts_q = select(func.count()).where(RiskAlert.acknowledged == False)
        incentive_q = select(func.sum(IncentiveEvent.amount)).where(
            IncentiveEvent.verified == False
        )

    total_patients = (await db.execute(patient_q)).scalar() or 0
    high_risk = (await db.execute(high_risk_q)).scalar() or 0
    unack_alerts = (await db.execute(alerts_q)).scalar() or 0
    pending_incentives = (await db.execute(incentive_q)).scalar() or 0

    return {
        "total_patients": total_patients,
        "high_risk_count": high_risk,
        "unacknowledged_alerts": unack_alerts,
        "pending_incentives": int(pending_incentives),
    }


@router.get("/high-risk-patients")
async def high_risk_patients(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List RED + PURPLE patients for the block officer heatmap."""
    result = await db.execute(
        select(Patient).where(
            Patient.current_risk_level.in_(["red", "purple"])
        )
    )
    patients = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "type": p.patient_type,
            "risk_level": p.current_risk_level,
            "risk_score": p.current_risk_score,
            "address": p.address,
            "phone": p.phone,
            "asha_id": p.asha_id,
        }
        for p in patients
    ]


@router.get("/alerts")
async def get_alerts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
):
    """Paginated unacknowledged alerts. page=1, page_size=20 by default."""
    offset = (page - 1) * page_size
    stmt = (
        select(RiskAlert, Patient.name)
        .join(Patient, RiskAlert.patient_id == Patient.id)
        .where(RiskAlert.acknowledged == False)
        .order_by(RiskAlert.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    if current_user.role == "asha":
        stmt = stmt.where(Patient.asha_id == current_user.id)

    # Total count for frontend pagination controls
    count_stmt = select(func.count()).select_from(
        select(RiskAlert)
        .join(Patient, RiskAlert.patient_id == Patient.id)
        .where(RiskAlert.acknowledged == False)
        .subquery()
    )
    if current_user.role == "asha":
        count_stmt = select(func.count()).select_from(
            select(RiskAlert)
            .join(Patient, RiskAlert.patient_id == Patient.id)
            .where(and_(RiskAlert.acknowledged == False,
                        Patient.asha_id == current_user.id))
            .subquery()
        )

    result = await db.execute(stmt)
    total = (await db.execute(count_stmt)).scalar() or 0
    rows = result.all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "alerts": [
            {
                "id": alert.id,
                "patient_name": name,
                "patient_id": alert.patient_id,
                "risk_level": alert.risk_level,
                "risk_score": alert.risk_score,
                "triggered_params": alert.triggered_params,
                "created_at": alert.created_at.isoformat() if alert.created_at else "",
            }
            for alert, name in rows
        ],
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(RiskAlert).where(RiskAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if alert:
        alert.acknowledged = True
        alert.acknowledged_by = current_user.id
        from datetime import datetime, timezone
        alert.acknowledged_at = datetime.now(timezone.utc)
        await db.commit()
    return {"status": "acknowledged"}


@router.get("/incentives")
async def get_incentives(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role == "asha":
        result = await db.execute(
            select(IncentiveEvent)
            .where(IncentiveEvent.asha_id == current_user.id)
            .order_by(IncentiveEvent.created_at.desc())
        )
    else:
        result = await db.execute(
            select(IncentiveEvent).order_by(IncentiveEvent.created_at.desc())
        )
    events = result.scalars().all()

    total = sum(e.amount for e in events)
    verified = sum(e.amount for e in events if e.verified)
    return {
        "events": [
            {
                "id": e.id,
                "type": e.event_type,
                "amount": e.amount,
                "patient_name": e.patient_name,
                "event_date": e.event_date,
                "verified": e.verified,
            }
            for e in events
        ],
        "total_earned": total,
        "total_verified": verified,
        "pending_payment": total - verified,
    }


@router.get("/export/hmis")
async def export_hmis_csv(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export visit data in HMIS-compatible CSV format for monthly reporting."""
    result = await db.execute(
        select(Visit, Patient.name, Patient.patient_type)
        .join(Patient, Visit.patient_id == Patient.id)
        .order_by(Visit.visit_date.desc())
        .limit(1000)
    )
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Visit Date", "Patient Name", "Type", "Visit Type",
        "Risk Level", "Risk Score", "Haemoglobin", "Systolic BP",
        "Diastolic BP", "MUAC (mm)", "Weight (kg)", "GPS Lat", "GPS Lng"
    ])
    for visit, pname, ptype in rows:
        v = visit.vitals or {}
        writer.writerow([
            visit.visit_date, pname, ptype, visit.visit_type,
            visit.risk_level, visit.risk_score,
            v.get("hemoglobin", ""), v.get("systolic_bp", ""),
            v.get("diastolic_bp", ""), v.get("muac_mm", ""),
            v.get("weight_kg", ""), visit.gps_lat, visit.gps_lng,
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=hmis_export.csv"},
    )


@router.get("/risk-distribution")
async def risk_distribution(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Count of patients per risk tier — used for donut chart."""
    result = await db.execute(select(Patient))
    patients = result.scalars().all()
    dist = {"green": 0, "yellow": 0, "red": 0, "purple": 0, "unknown": 0}
    for p in patients:
        key = p.current_risk_level or "unknown"
        dist[key] = dist.get(key, 0) + 1
    return dist


@router.get("/weekly-trend")
async def weekly_trend(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Average risk score per week for the last 8 weeks — used for line chart.
    Uses SQL AVG aggregation (no in-memory load) for scalability.
    """
    from datetime import date, timedelta
    today = date.today()
    weeks = []
    for i in range(7, -1, -1):
        week_start = today - timedelta(days=today.weekday() + 7 * i)
        week_end   = week_start + timedelta(days=6)
        # Single aggregation query — O(1) memory regardless of visit count
        agg = await db.execute(
            select(
                func.avg(Visit.risk_score).label("avg_score"),
                func.count(Visit.id).label("visit_count"),
            ).where(
                Visit.visit_date >= str(week_start),
                Visit.visit_date <= str(week_end),
                Visit.risk_score.isnot(None),
            )
        )
        row = agg.one()
        avg_score = round(float(row.avg_score), 1) if row.avg_score else 0
        weeks.append({
            "week": str(week_start),
            "label": f"W{8 - i}",
            "avg_score": avg_score,
            "visit_count": row.visit_count or 0,
        })
    return weeks


@router.get("/anc-coverage")
async def anc_coverage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """ANC contact coverage — % of maternal patients with ≥4 ANC visits.
    Uses a single LEFT OUTER JOIN + GROUP BY — eliminates N+1 query pattern.
    """
    # Single query: all maternal patients + their ANC visit counts
    result = await db.execute(
        select(
            Patient.id,
            Patient.name,
            func.count(Visit.id).label("anc_count"),
        )
        .outerjoin(
            Visit,
            and_(
                Visit.patient_id == Patient.id,
                Visit.visit_type.in_(["anc", "anc_registration"]),
            ),
        )
        .where(Patient.patient_type == "maternal")
        .group_by(Patient.id, Patient.name)
    )
    rows = result.all()

    coverage = [
        {
            "patient_id": row.id,
            "name": row.name,
            "anc_count": row.anc_count,
            "target": 8,
            "met_minimum": row.anc_count >= 4,
        }
        for row in rows
    ]

    total = len(coverage)
    met = sum(1 for c in coverage if c["met_minimum"])
    return {
        "total_maternal": total,
        "met_4_contacts": met,
        "coverage_pct": round(met / total * 100, 1) if total else 0,
        "patients": coverage,
    }
