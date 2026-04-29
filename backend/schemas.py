from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, model_validator


# --- Auth ---

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    name: str


# --- User ---

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    role: str = "asha"
    area_code: Optional[str] = None
    area_name: Optional[str] = None
    district: Optional[str] = None
    block: Optional[str] = None


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str
    area_name: Optional[str] = None
    block: Optional[str] = None
    district: Optional[str] = None

    model_config = {"from_attributes": True}


# --- Patient ---

class PatientCreate(BaseModel):
    id: str
    patient_type: str  # maternal | child
    name: str
    age: Optional[int] = None
    dob: Optional[str] = None
    sex: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    husband_name: Optional[str] = None
    linked_patient_id: Optional[str] = None
    # Maternal fields
    lmp: Optional[str] = None
    edd: Optional[str] = None
    gravida: Optional[int] = None
    para: Optional[int] = None
    blood_group: Optional[str] = None
    # Child fields
    birth_date: Optional[str] = None
    birth_weight_kg: Optional[float] = None


class PatientOut(PatientCreate):
    asha_id: str
    current_risk_level: Optional[str] = None
    current_risk_score: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# --- Visit ---

# Vital sign clinical bounds (WHO / standard lab reference ranges)
_VITAL_BOUNDS: dict[str, tuple[float, float]] = {
    "hemoglobin":       (2.0,  25.0),   # g/dL — impossible outside this range
    "systolic_bp":      (40,   300),     # mmHg
    "diastolic_bp":     (20,   200),     # mmHg
    "weight_kg":        (0.5,  250),     # kg — covers neonates to obese adults
    "gestational_week": (1,    45),      # weeks
    "fbs":              (0,    600),     # mg/dL fasting blood sugar
    "muac_mm":          (50,   400),     # mm
    "temperature_c":    (30.0, 43.0),   # °C
    "height_cm":        (20,   250),     # cm
    "bmi_booking":      (10,   80),      # kg/m²
}


class VisitCreate(BaseModel):
    id: str
    patient_id: str
    visit_type: str
    visit_date: str
    vitals: dict = {}
    observations: dict = {}
    gps_lat: Optional[float] = None
    gps_lng: Optional[float] = None
    device_id: Optional[str] = None
    updated_at: Optional[float] = None  # Unix timestamp

    @model_validator(mode="after")
    def validate_vitals(self) -> "VisitCreate":
        """Reject physiologically impossible vital sign values."""
        errors: list[str] = []
        for field, (lo, hi) in _VITAL_BOUNDS.items():
            val = self.vitals.get(field)
            if val is None:
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                errors.append(f"{field}: must be a number (got {val!r})")
                continue
            if not (lo <= v <= hi):
                errors.append(
                    f"{field}: value {v} is outside clinical range [{lo}, {hi}]"
                )
        # BP sanity: systolic must be > diastolic
        sys = self.vitals.get("systolic_bp")
        dia = self.vitals.get("diastolic_bp")
        if sys is not None and dia is not None:
            try:
                if float(sys) <= float(dia):
                    errors.append(
                        f"systolic_bp ({sys}) must be greater than diastolic_bp ({dia})"
                    )
            except (TypeError, ValueError):
                pass
        if errors:
            raise ValueError("Invalid vitals: " + "; ".join(errors))
        return self


class VisitOut(BaseModel):
    id: str
    patient_id: str
    asha_id: str
    visit_type: str
    visit_date: str
    vitals: dict
    observations: dict
    risk_level: Optional[str] = None
    risk_score: Optional[int] = None
    risk_triggered: Optional[list] = None
    gps_lat: Optional[float] = None
    gps_lng: Optional[float] = None
    created_at: Optional[datetime] = None
    ml_forecast: Optional[dict] = None

    model_config = {"from_attributes": True}


# --- Sync ---

class SyncPayload(BaseModel):
    device_id: str
    last_sync_ts: float  # Unix timestamp
    records: list[dict]  # mixed entity_type records


class SyncResponse(BaseModel):
    status: str
    created: int
    updated: int
    conflicts: int
    server_changes: list[dict]
    server_ts: float


# --- Risk ---

class RiskResponse(BaseModel):
    score: int
    level: str
    action: str
    triggered_parameters: list[str]
    requires_immediate_alert: bool
    notify_block_officer: bool


# --- Dashboard ---

class DashboardStats(BaseModel):
    total_patients: int
    high_risk_count: int
    unacknowledged_alerts: int
    ashas_active: int
    pending_incentives: int
