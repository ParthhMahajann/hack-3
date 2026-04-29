"""
SQLAlchemy models — mirrors the actual MCP (Mother Child Protection) card fields
used by ASHA workers in the field. Schema validated against RCH-II register format.
"""

from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, JSON,
    ForeignKey, Text, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(15), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(200))
    # role: asha | anm | block_officer | admin
    role: Mapped[str] = mapped_column(String(20), default="asha")
    area_code: Mapped[str] = mapped_column(String(50), nullable=True)
    area_name: Mapped[str] = mapped_column(String(200), nullable=True)
    district: Mapped[str] = mapped_column(String(100), nullable=True)
    block: Mapped[str] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    push_subscription: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # patient_type: maternal | child
    patient_type: Mapped[str] = mapped_column(String(10))
    asha_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))

    # Demographics (MCP card fields)
    name: Mapped[str] = mapped_column(String(200))
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dob: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sex: Mapped[str | None] = mapped_column(String(1), nullable=True)  # M/F
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    husband_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Maternal-specific (MCP card — maternal section)
    lmp: Mapped[str | None] = mapped_column(String(20), nullable=True)   # last menstrual period
    edd: Mapped[str | None] = mapped_column(String(20), nullable=True)   # expected delivery date
    gravida: Mapped[int | None] = mapped_column(Integer, nullable=True)
    para: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(5), nullable=True)

    # Child-specific (MCP card — child section)
    birth_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    birth_weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Mother-child linking
    linked_patient_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("patients.id"), nullable=True
    )

    # Current risk state (denormalised for dashboard queries)
    current_risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    current_risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    device_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    visits: Mapped[list["Visit"]] = relationship("Visit", back_populates="patient",
                                                  lazy="select")


class Visit(Base):
    """
    Immutable visit event log.
    Each ANC/PNC/home visit is a separate record — never updated in place.
    Vitals and observations stored as JSON for flexibility (form fields evolve).
    """
    __tablename__ = "visits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"))
    asha_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))

    # visit_type: anc | pnc | home_visit | vhnd | delivery | anc_registration
    visit_type: Mapped[str] = mapped_column(String(30))
    visit_date: Mapped[str] = mapped_column(String(20))

    # Vitals — stored as JSON (MCP card vitals section)
    # Keys: hemoglobin, systolic_bp, diastolic_bp, weight_kg, height_cm,
    #       muac_mm, temperature_c, spo2, fbs, proteinuria
    vitals: Mapped[dict] = mapped_column(JSON, default=dict)

    # Observations — stored as JSON (MCP card observation section)
    # Keys: edema, fetal_movement, danger_signs, vaccines_given,
    #       delivery_place, breastfeeding_ok, referral_escorted, etc.
    observations: Mapped[dict] = mapped_column(JSON, default=dict)

    # Risk output (computed at visit time)
    risk_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_triggered: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # GPS — proves field visit (anti-fraud for incentive verification)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lng: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Referral
    referral_issued: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Sync metadata
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    patient: Mapped["Patient"] = relationship("Patient", back_populates="visits")


class RiskAlert(Base):
    """Dispatched alerts for RED/PURPLE cases."""
    __tablename__ = "risk_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"))
    visit_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(10))
    risk_score: Mapped[int] = mapped_column(Integer)
    triggered_params: Mapped[list] = mapped_column(JSON, default=list)
    channels_used: Mapped[list] = mapped_column(JSON, default=list)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class IncentiveEvent(Base):
    """Earned incentive events derived from visit records."""
    __tablename__ = "incentive_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asha_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    patient_id: Mapped[str] = mapped_column(String(36))
    patient_name: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(50))
    amount: Mapped[int] = mapped_column(Integer)
    event_date: Mapped[str] = mapped_column(String(20))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SyncConflict(Base):
    """Conflict log — reviewed by ANM at weekly meeting."""
    __tablename__ = "sync_conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[str] = mapped_column(String(36))
    device_id: Mapped[str] = mapped_column(String(100))
    client_payload: Mapped[dict] = mapped_column(JSON)
    server_payload: Mapped[dict] = mapped_column(JSON)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    conflict_ts: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SyncMeta(Base):
    """Track per-device sync state."""
    __tablename__ = "sync_meta"

    device_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sync_count: Mapped[int] = mapped_column(Integer, default=0)
