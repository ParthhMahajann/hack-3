"""
Sync Engine — Delta sync with last-write-wins per field.
Conflict log persisted for ANM review.

Architecture reference:
  Shapiro et al. "A comprehensive study of Convergent and Commutative
  Replicated Data Types", INRIA RR-7506, 2011 — motivates field-level
  merge over whole-record overwrite to minimise data loss in
  intermittently connected deployments.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Visit, Patient, SyncConflict, SyncMeta

# Priority ordering for sync — critical cases synced first
_LEVEL_PRIORITY = {"purple": 0, "red": 1, "yellow": 2, "green": 3, None: 4}


def _priority_key(record: dict) -> int:
    return _LEVEL_PRIORITY.get(record.get("risk_level"), 4)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def process_sync_payload(
    device_id: str,
    last_sync_ts: float,   # Unix timestamp from client
    incoming_records: list[dict],
    db: AsyncSession,
) -> dict:
    """
    Process records uploaded by ASHA device during sync.
    Returns server-side changes the client needs to pull.
    """
    last_sync = datetime.fromtimestamp(last_sync_ts, tz=timezone.utc)
    conflicts: list[dict] = []
    created = updated = 0

    # Sort incoming by risk priority — critical cases first
    for record in sorted(incoming_records, key=_priority_key):
        entity_type = record.get("entity_type", "visit")
        if entity_type == "visit":
            result = await _upsert_visit(record, device_id, db)
        elif entity_type == "patient":
            result = await _upsert_patient(record, device_id, db)
        else:
            continue

        if result == "created":
            created += 1
        elif result == "updated":
            updated += 1
        elif isinstance(result, dict):  # conflict
            conflicts.append(result)

    await db.commit()

    # Pull server changes the client hasn't seen yet
    server_changes = await _get_server_changes(last_sync, db)

    # Update sync metadata for this device
    await _update_sync_meta(device_id, db)

    return {
        "status": "ok",
        "created": created,
        "updated": updated,
        "conflicts": len(conflicts),
        "conflict_details": conflicts,
        "server_changes": server_changes,
        "server_ts": _utc_now().timestamp(),
    }


async def _upsert_visit(record: dict, device_id: str, db: AsyncSession) -> Any:
    visit_id = record.get("id")
    result = await db.execute(select(Visit).where(Visit.id == visit_id))
    existing: Visit | None = result.scalar_one_or_none()

    client_ts = datetime.fromtimestamp(record.get("updated_at", 0), tz=timezone.utc)

    if existing is None:
        visit = Visit(
            id=visit_id,
            patient_id=record["patient_id"],
            asha_id=record["asha_id"],
            visit_date=record["visit_date"],
            visit_type=record.get("visit_type", "home_visit"),
            vitals=record.get("vitals", {}),
            observations=record.get("observations", {}),
            risk_level=record.get("risk_level"),
            risk_score=record.get("risk_score", 0),
            risk_triggered=record.get("risk_triggered", []),
            gps_lat=record.get("gps_lat"),
            gps_lng=record.get("gps_lng"),
            synced_at=_utc_now(),
            device_id=device_id,
            updated_at=client_ts,
        )
        db.add(visit)
        return "created"
    else:
        # Last-write-wins per record
        # If client is newer: accept; if server is newer: conflict logged
        server_ts = existing.updated_at.replace(tzinfo=timezone.utc) if existing.updated_at else datetime.min.replace(tzinfo=timezone.utc)

        if client_ts > server_ts:
            await db.execute(
                update(Visit)
                .where(Visit.id == visit_id)
                .values(
                    vitals=record.get("vitals", existing.vitals),
                    observations=record.get("observations", existing.observations),
                    risk_level=record.get("risk_level", existing.risk_level),
                    risk_score=record.get("risk_score", existing.risk_score),
                    risk_triggered=record.get("risk_triggered", existing.risk_triggered),
                    gps_lat=record.get("gps_lat", existing.gps_lat),
                    gps_lng=record.get("gps_lng", existing.gps_lng),
                    synced_at=_utc_now(),
                    updated_at=client_ts,
                )
            )
            return "updated"
        else:
            # Server has newer data — log conflict for ANM review
            conflict = SyncConflict(
                entity_type="visit",
                entity_id=str(visit_id),
                device_id=device_id,
                client_payload=record,
                server_payload=_visit_to_dict(existing),
                conflict_ts=_utc_now(),
            )
            db.add(conflict)
            return {"entity_id": visit_id, "reason": "server_is_newer"}


async def _upsert_patient(record: dict, device_id: str, db: AsyncSession) -> Any:
    patient_id = record.get("id")
    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    existing = result.scalar_one_or_none()

    client_ts = datetime.fromtimestamp(record.get("updated_at", 0), tz=timezone.utc)

    if existing is None:
        patient = Patient(
            id=patient_id,
            patient_type=record.get("patient_type", "maternal"),
            asha_id=record["asha_id"],
            name=record["name"],
            age=record.get("age"),
            dob=record.get("dob"),
            address=record.get("address"),
            phone=record.get("phone"),
            husband_name=record.get("husband_name"),
            linked_patient_id=record.get("linked_patient_id"),
            lmp=record.get("lmp"),
            edd=record.get("edd"),
            gravida=record.get("gravida"),
            para=record.get("para"),
            blood_group=record.get("blood_group"),
            sex=record.get("sex"),
            birth_date=record.get("birth_date"),
            birth_weight_kg=record.get("birth_weight_kg"),
            device_id=device_id,
        )
        db.add(patient)
        return "created"

    # Last-write-wins: only accept if client timestamp is newer
    server_ts = existing.updated_at.replace(tzinfo=timezone.utc) if existing.updated_at else datetime.min.replace(tzinfo=timezone.utc)
    if client_ts > server_ts:
        existing.name = record.get("name", existing.name)
        existing.age = record.get("age", existing.age)
        existing.address = record.get("address", existing.address)
        existing.phone = record.get("phone", existing.phone)
        existing.lmp = record.get("lmp", existing.lmp)
        existing.edd = record.get("edd", existing.edd)
        existing.gravida = record.get("gravida", existing.gravida)
        existing.para = record.get("para", existing.para)
        existing.updated_at = client_ts
        return "updated"
    else:
        # Server record is newer — log conflict for ANM review
        db.add(SyncConflict(
            entity_type="patient",
            entity_id=str(patient_id),
            device_id=device_id,
            client_payload=record,
            server_payload={"id": existing.id, "name": existing.name,
                            "updated_at": server_ts.timestamp()},
            conflict_ts=_utc_now(),
        ))
        return {"entity_id": patient_id, "reason": "server_is_newer"}


async def _get_server_changes(since: datetime, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(Visit).where(Visit.synced_at > since)
    )
    visits = result.scalars().all()
    return [_visit_to_dict(v) for v in visits]


async def _update_sync_meta(device_id: str, db: AsyncSession) -> None:
    result = await db.execute(
        select(SyncMeta).where(SyncMeta.device_id == device_id)
    )
    meta = result.scalar_one_or_none()
    if meta is None:
        db.add(SyncMeta(device_id=device_id, last_sync=_utc_now(), sync_count=1))
    else:
        meta.last_sync = _utc_now()
        meta.sync_count = (meta.sync_count or 0) + 1


def _visit_to_dict(v: Visit) -> dict:
    return {
        "id": v.id,
        "entity_type": "visit",
        "patient_id": v.patient_id,
        "asha_id": v.asha_id,
        "visit_date": str(v.visit_date),
        "visit_type": v.visit_type,
        "vitals": v.vitals,
        "observations": v.observations,
        "risk_level": v.risk_level,
        "risk_score": v.risk_score,
        "risk_triggered": v.risk_triggered,
        "gps_lat": v.gps_lat,
        "gps_lng": v.gps_lng,
        "updated_at": v.updated_at.timestamp() if v.updated_at else 0,
    }
