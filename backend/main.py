"""
ASHA Saheli — Digital Field Diary for Frontline Health Workers
FastAPI backend serving the offline-first PWA.
"""

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.database import init_db
from backend.routers import auth, patients, visits, sync, dashboard
from backend.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _seed_demo_data()
    yield


app = FastAPI(
    title="ASHA Saheli",
    description="Offline-first field diary for ASHA workers",
    version="1.0.0",
    lifespan=lifespan,
)

# Static files + templates
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend" / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "frontend" / "templates"))

# Routers
app.include_router(auth.router)
app.include_router(patients.router)
app.include_router(visits.router)
app.include_router(sync.router)
app.include_router(dashboard.router)


# ---------------------------------------------------------------------------
# PWA page routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/app", response_class=HTMLResponse)
async def asha_dashboard(request: Request):
    return templates.TemplateResponse("asha/dashboard.html", {"request": request})


@app.get("/app/patient/new", response_class=HTMLResponse)
async def patient_form(request: Request):
    return templates.TemplateResponse("asha/patient_form.html", {"request": request})


@app.get("/app/visit/new", response_class=HTMLResponse)
async def visit_form(request: Request):
    return templates.TemplateResponse("asha/visit_form.html", {"request": request})


@app.get("/officer", response_class=HTMLResponse)
async def officer_dashboard(request: Request):
    return templates.TemplateResponse("officer/dashboard.html", {"request": request})


@app.get("/app/incentives", response_class=HTMLResponse)
async def incentives(request: Request):
    return templates.TemplateResponse("asha/incentives.html", {"request": request})


# ---------------------------------------------------------------------------
# Demo seed data (shown to judges without login friction)
# ---------------------------------------------------------------------------

async def _seed_demo_data():
    """Seed realistic demo patients and visits so the dashboard is populated."""
    from backend.database import AsyncSessionLocal
    from backend.models import User, Patient, Visit, RiskAlert
    from backend.routers.auth import _hash_password
    from datetime import datetime, timezone
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        # Check if already seeded
        existing = await db.execute(select(User).where(User.email == "asha1@demo.in"))
        if existing.scalar_one_or_none():
            return

        # --- Users ---
        asha_id = str(uuid.uuid4())
        officer_id = str(uuid.uuid4())

        asha = User(id=asha_id, name="Sunita Devi", email="asha1@demo.in",
                    phone="9876543210", hashed_password=_hash_password("asha123"),
                    role="asha", area_name="Rampur Village", block="Sadar",
                    district="Varanasi")
        officer = User(id=officer_id, name="Dr. Rajesh Kumar", email="officer@demo.in",
                       phone="9876500001", hashed_password=_hash_password("officer123"),
                       role="block_officer", block="Sadar", district="Varanasi")
        db.add_all([asha, officer])

        # --- Patients ---
        patients_data = [
            # PURPLE case: severe anaemia + hypertension + edema
            dict(id=str(uuid.uuid4()), patient_type="maternal", asha_id=asha_id,
                 name="Meena Yadav", age=19, address="12, Rampur", phone="9871234560",
                 lmp="2024-09-01", edd="2025-06-08", gravida=1, para=0,
                 current_risk_level="purple", current_risk_score=85),
            # RED case: pre-eclampsia range BP
            dict(id=str(uuid.uuid4()), patient_type="maternal", asha_id=asha_id,
                 name="Sita Kumari", age=28, address="45, Rampur", phone="9871234561",
                 lmp="2024-10-15", edd="2025-07-22", gravida=2, para=1,
                 current_risk_level="red", current_risk_score=65),
            # YELLOW case: moderate anaemia
            dict(id=str(uuid.uuid4()), patient_type="maternal", asha_id=asha_id,
                 name="Radha Devi", age=24, address="78, Rampur", phone="9871234562",
                 lmp="2024-11-01", edd="2025-08-08", gravida=1, para=0,
                 current_risk_level="yellow", current_risk_score=35),
            # GREEN case
            dict(id=str(uuid.uuid4()), patient_type="maternal", asha_id=asha_id,
                 name="Priya Singh", age=22, address="22, Rampur",
                 lmp="2024-12-01", edd="2025-09-08", gravida=1, para=0,
                 current_risk_level="green", current_risk_score=10),
            # Child SAM case
            dict(id=str(uuid.uuid4()), patient_type="child", asha_id=asha_id,
                 name="Raju (M/8mo)", sex="M", birth_date="2024-08-01",
                 address="12, Rampur", current_risk_level="purple", current_risk_score=90),
            # Child MAM case
            dict(id=str(uuid.uuid4()), patient_type="child", asha_id=asha_id,
                 name="Geeta (F/14mo)", sex="F", birth_date="2024-02-01",
                 address="56, Rampur", current_risk_level="yellow", current_risk_score=40),
        ]

        patient_ids = []
        for pd in patients_data:
            p = Patient(**pd)
            db.add(p)
            patient_ids.append(pd["id"])

        # --- Sample visits ---
        now = datetime.now(timezone.utc)
        visits_data = [
            dict(id=str(uuid.uuid4()), patient_id=patient_ids[0], asha_id=asha_id,
                 visit_type="anc", visit_date="2025-04-28",
                 vitals={"hemoglobin": 6.2, "systolic_bp": 148, "diastolic_bp": 95,
                         "weight_kg": 48.0},
                 observations={"edema_generalised": True, "missed_anc_visits": 2},
                 risk_level="purple", risk_score=85,
                 risk_triggered=["Severe anaemia: Hb=6.2 g/dL", "Pre-eclampsia range BP: 148/95",
                                 "Generalised oedema", "Missed ANC contacts: 2"],
                 gps_lat=25.3176, gps_lng=82.9739,
                 synced_at=now, updated_at=now),
            dict(id=str(uuid.uuid4()), patient_id=patient_ids[1], asha_id=asha_id,
                 visit_type="anc", visit_date="2025-04-27",
                 vitals={"hemoglobin": 9.5, "systolic_bp": 142, "diastolic_bp": 92},
                 observations={"proteinuria_2plus": True},
                 risk_level="red", risk_score=65,
                 risk_triggered=["Pre-eclampsia range BP: 142/92", "Proteinuria ≥2+",
                                 "Moderate anaemia: Hb=9.5 g/dL"],
                 gps_lat=25.3180, gps_lng=82.9745,
                 synced_at=now, updated_at=now),
            dict(id=str(uuid.uuid4()), patient_id=patient_ids[4], asha_id=asha_id,
                 visit_type="home_visit", visit_date="2025-04-26",
                 vitals={"muac_mm": 108, "weight_kg": 6.1},
                 observations={"fever_days": 0, "breastfeeding_ok": True},
                 risk_level="purple", risk_score=90,
                 risk_triggered=["SAM: MUAC=108mm (<115mm)", "Severe underweight: WAZ=-3.4"],
                 gps_lat=25.3178, gps_lng=82.9740,
                 synced_at=now, updated_at=now),
        ]

        for vd in visits_data:
            db.add(Visit(**vd))

        # --- Alerts ---
        db.add(RiskAlert(
            patient_id=patient_ids[0], risk_level="purple", risk_score=85,
            triggered_params=["Severe anaemia", "Pre-eclampsia range BP"],
            channels_used=["in_app"]
        ))
        db.add(RiskAlert(
            patient_id=patient_ids[1], risk_level="red", risk_score=65,
            triggered_params=["Pre-eclampsia BP", "Proteinuria ≥2+"],
            channels_used=["in_app"]
        ))
        db.add(RiskAlert(
            patient_id=patient_ids[4], risk_level="purple", risk_score=90,
            triggered_params=["SAM: MUAC=108mm"],
            channels_used=["in_app"]
        ))

        await db.commit()
