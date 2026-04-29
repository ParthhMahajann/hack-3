from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Patient, User
from backend.schemas import PatientCreate, PatientOut
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/", response_model=list[PatientOut])
async def list_patients(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role == "asha":
        result = await db.execute(
            select(Patient).where(Patient.asha_id == current_user.id)
        )
    else:
        result = await db.execute(select(Patient))
    return result.scalars().all()


@router.post("/", response_model=PatientOut, status_code=201)
async def create_patient(
    data: PatientCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(Patient).where(Patient.id == data.id))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Patient ID already exists")

    patient = Patient(**data.model_dump(), asha_id=current_user.id)
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return patient


@router.get("/{patient_id}", response_model=PatientOut)
async def get_patient(
    patient_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(404, "Patient not found")
    return patient
