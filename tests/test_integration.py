"""
Integration tests — full pipeline: API → DB → risk engine → alerts → dashboard.
Uses FastAPI TestClient with in-memory SQLite (no server required).
"""

import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from backend.main import app
from backend.database import Base, get_db
from backend.models import User
from backend.routers.auth import _hash_password

# ── In-memory test database ──────────────────────────────────────────────────

TEST_DB = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB, connect_args={"check_same_thread": False})
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSession() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="module")
async def seeded_users():
    """Create one ASHA and one Block Officer for tests."""
    async with TestSession() as db:
        asha_id = str(uuid.uuid4())
        officer_id = str(uuid.uuid4())
        db.add(User(
            id=asha_id, name="Test ASHA", email="testasha@test.in",
            hashed_password=_hash_password("pass123"),
            role="asha", area_name="Test Village", block="Test Block", district="Test Dist"
        ))
        db.add(User(
            id=officer_id, name="Test Officer", email="testofficer@test.in",
            hashed_password=_hash_password("pass123"),
            role="block_officer"
        ))
        await db.commit()
    return {"asha_id": asha_id, "officer_id": officer_id}


async def get_token(client, email, password):
    r = await client.post("/auth/token",
                          data={"username": email, "password": password})
    return r.json()["access_token"]


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_and_login():
    """Auth flow: register → login → get /me."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/auth/register", json={
            "name": "New ASHA", "email": "new@test.in",
            "password": "secret123", "role": "asha"
        })
        assert r.status_code == 201

        token = await get_token(c, "new@test.in", "secret123")
        me = await c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["role"] == "asha"


@pytest.mark.asyncio
async def test_create_maternal_patient(seeded_users):
    """ASHA registers a maternal patient — appears in patient list."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = await get_token(c, "testasha@test.in", "pass123")
        patient_id = "pat-" + str(uuid.uuid4())[:8]

        r = await c.post("/patients/", json={
            "id": patient_id, "patient_type": "maternal",
            "name": "Priya Test", "age": 22, "lmp": "2025-01-01",
            "edd": "2025-10-08"
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201

        patients = await c.get("/patients/", headers={"Authorization": f"Bearer {token}"})
        assert any(p["id"] == patient_id for p in patients.json())


@pytest.mark.asyncio
async def test_purple_visit_creates_alert(seeded_users):
    """
    Full pipeline: log visit with PURPLE vitals →
    risk engine fires → RiskAlert created → appears on dashboard.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = await get_token(c, "testasha@test.in", "pass123")

        # Register patient
        patient_id = "pat-purple-" + str(uuid.uuid4())[:6]
        await c.post("/patients/", json={
            "id": patient_id, "patient_type": "maternal",
            "name": "High Risk Patient", "age": 19,
            "lmp": "2025-01-01", "edd": "2025-10-08"
        }, headers={"Authorization": f"Bearer {token}"})

        # Log visit with severe anaemia + pre-eclampsia BP = PURPLE
        visit_id = "vis-" + str(uuid.uuid4())[:8]
        r = await c.post("/visits/", json={
            "id": visit_id,
            "patient_id": patient_id,
            "visit_type": "anc",
            "visit_date": "2025-04-29",
            "vitals": {
                "hemoglobin": 6.0,        # severe anaemia → +60
                "systolic_bp": 148,        # pre-eclampsia → +35
                "diastolic_bp": 94,
            },
            "observations": {
                "edema_generalised": True,   # +15
                "proteinuria_2plus": True,   # +20 → triad → force PURPLE
                "missed_anc_visits": 2       # +10
            },
            "updated_at": 1700000000.0
        }, headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 201
        visit_data = r.json()
        assert visit_data["risk_level"] == "purple", f"Expected purple, got {visit_data['risk_level']}"
        assert visit_data["risk_score"] >= 80

        # Alert must appear on dashboard
        officer_token = await get_token(c, "testofficer@test.in", "pass123")
        alerts = await c.get("/dashboard/alerts",
                             headers={"Authorization": f"Bearer {officer_token}"})
        assert alerts.status_code == 200
        alert_patient_ids = [a["patient_id"] for a in alerts.json()["alerts"]]
        assert patient_id in alert_patient_ids, "PURPLE visit did not create a dashboard alert"


@pytest.mark.asyncio
async def test_green_visit_no_alert(seeded_users):
    """Normal vitals → GREEN → no alert created."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = await get_token(c, "testasha@test.in", "pass123")
        patient_id = "pat-green-" + str(uuid.uuid4())[:6]

        await c.post("/patients/", json={
            "id": patient_id, "patient_type": "maternal",
            "name": "Healthy Patient", "age": 24,
        }, headers={"Authorization": f"Bearer {token}"})

        before_alerts = await c.get("/dashboard/alerts",
                                    headers={"Authorization": f"Bearer {token}"})
        count_before = len(before_alerts.json()["alerts"])

        await c.post("/visits/", json={
            "id": "vis-green-" + str(uuid.uuid4())[:6],
            "patient_id": patient_id,
            "visit_type": "anc",
            "visit_date": "2025-04-29",
            "vitals": {"hemoglobin": 11.5, "systolic_bp": 110, "diastolic_bp": 70},
            "observations": {},
            "updated_at": 1700000000.0
        }, headers={"Authorization": f"Bearer {token}"})

        after_alerts = await c.get("/dashboard/alerts",
                                   headers={"Authorization": f"Bearer {token}"})
        assert len(after_alerts.json()["alerts"]) == count_before, "Green visit should not create an alert"


@pytest.mark.asyncio
async def test_role_isolation(seeded_users):
    """ASHA only sees own patients; cannot see other ASHA's patients."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Register second ASHA
        await c.post("/auth/register", json={
            "name": "Other ASHA", "email": "other@test.in",
            "password": "pass123", "role": "asha"
        })
        token1 = await get_token(c, "testasha@test.in", "pass123")
        token2 = await get_token(c, "other@test.in", "pass123")

        # ASHA2 registers a patient
        patient_id = "pat-other-" + str(uuid.uuid4())[:6]
        await c.post("/patients/", json={
            "id": patient_id, "patient_type": "maternal", "name": "Other's Patient"
        }, headers={"Authorization": f"Bearer {token2}"})

        # ASHA1 should NOT see ASHA2's patient
        r = await c.get("/patients/", headers={"Authorization": f"Bearer {token1}"})
        ids = [p["id"] for p in r.json()]
        assert patient_id not in ids, "ASHA should not see another ASHA's patient"


@pytest.mark.asyncio
async def test_hmis_export_csv(seeded_users):
    """HMIS export returns valid CSV with correct headers."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = await get_token(c, "testasha@test.in", "pass123")
        r = await c.get("/dashboard/export/hmis",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        first_line = r.text.split("\n")[0]
        assert "Visit Date" in first_line
        assert "Risk Level" in first_line
        assert "Haemoglobin" in first_line


@pytest.mark.asyncio
async def test_sync_endpoint(seeded_users):
    """Sync payload from device → server processes records."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        token = await get_token(c, "testasha@test.in", "pass123")

        # Register patient first
        patient_id = "pat-sync-" + str(uuid.uuid4())[:6]
        await c.post("/patients/", json={
            "id": patient_id, "patient_type": "maternal", "name": "Sync Patient"
        }, headers={"Authorization": f"Bearer {token}"})

        # Push offline-queued visit via sync endpoint
        r = await c.post("/sync/", json={
            "device_id": "test-device-001",
            "last_sync_ts": 0.0,
            "records": [{
                "entity_type": "visit",
                "id": "vis-sync-" + str(uuid.uuid4())[:6],
                "patient_id": patient_id,
                "asha_id": seeded_users["asha_id"],
                "visit_type": "home_visit",
                "visit_date": "2025-04-28",
                "vitals": {"hemoglobin": 9.0, "systolic_bp": 115, "diastolic_bp": 75},
                "observations": {},
                "risk_level": "yellow",
                "risk_score": 20,
                "updated_at": 1700000001.0
            }]
        }, headers={"Authorization": f"Bearer {token}"})

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["created"] >= 1
