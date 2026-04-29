"""
Sync Engine -- Field-level LWW Register merge with conflict logging.
Implements a practical subset of CRDTs for intermittent connectivity.

Architecture reference:
  Shapiro et al. "A comprehensive study of Convergent and Commutative
  Replicated Data Types", INRIA RR-7506, 2011.

  Specifically we implement a **LWW-Register per field** (Section 3.2.3 of
  Shapiro et al.):  each field in vitals/observations carries an implicit
  timestamp from its enclosing record.  When a merge is needed the algorithm
  iterates every key in both the client and server JSON dicts, keeping the
  value from whichever side has the later timestamp.  Fields present only on
  one side are always preserved (union semantics -- equivalent to a Grow-Only
  Set merge for new keys).

  This is a concrete improvement over whole-record LWW: if ASHA-A records
  hemoglobin on Device-1 while ASHA-B records blood pressure on Device-2,
  both values survive the merge.  Under whole-record LWW one would be lost.

  Conflicts (both sides modified the same key to different values) are
  persisted in SyncConflict for ANM review at the next weekly meeting.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Visit, Patient, SyncConflict, SyncMeta

# Priority ordering for sync -- critical cases synced first
_LEVEL_PRIORITY = {"purple": 0, "red": 1, "yellow": 2, "green": 3, None: 4}


def _priority_key(record: dict) -> int:
    return _LEVEL_PRIORITY.get(record.get("risk_level"), 4)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Field-level LWW merge  (Shapiro et al. Section 3.2.3)
# ---------------------------------------------------------------------------

def field_level_merge(
    server_dict: dict,
    client_dict: dict,
    server_ts: datetime,
    client_ts: datetime,
) -> tuple[dict, list[dict]]:
    """
    Merge two JSON dicts (vitals or observations) field by field.

    Rules (LWW-Register per key):
      - Key only on server  --> keep server value  (no conflict)
      - Key only on client  --> accept client value (Grow-Only Set union)
      - Key on both, same value --> keep (no conflict)
      - Key on both, different value --> keep the *newer* timestamp's value,
        log a conflict record for the losing value

    Returns:
        (merged_dict, conflict_list)
    """
    merged = dict(server_dict)   # start from server state
    conflicts: list[dict] = []
    all_keys = set(list(server_dict.keys()) + list(client_dict.keys()))

    for key in all_keys:
        s_val = server_dict.get(key)
        c_val = client_dict.get(key)

        if key not in server_dict:
            # New field from client -- Grow-Only Set semantics: always accept
            merged[key] = c_val
        elif key not in client_dict:
            # Field only on server -- keep server value (client never had it)
            pass
        elif s_val == c_val:
            # Same value on both sides -- no action needed
            pass
        else:
            # Genuine conflict: same key, different values
            if client_ts > server_ts:
                merged[key] = c_val   # client wins
            # else: server wins, merged already has server value

            conflicts.append({
                "field": key,
                "server_value": s_val,
                "client_value": c_val,
                "winner": "client" if client_ts > server_ts else "server",
            })

    return merged, conflicts


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

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

    # Sort incoming by risk priority -- critical cases first
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


# ---------------------------------------------------------------------------
# Visit upsert with field-level merge
# ---------------------------------------------------------------------------

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

    # ── Field-level LWW merge (Shapiro et al. Section 3.2.3) ──
    server_ts = (
        existing.updated_at.replace(tzinfo=timezone.utc)
        if existing.updated_at
        else datetime.min.replace(tzinfo=timezone.utc)
    )

    # Merge vitals and observations dicts field by field
    merged_vitals, vitals_conflicts = field_level_merge(
        existing.vitals or {}, record.get("vitals", {}), server_ts, client_ts,
    )
    merged_obs, obs_conflicts = field_level_merge(
        existing.observations or {}, record.get("observations", {}), server_ts, client_ts,
    )

    all_field_conflicts = vitals_conflicts + obs_conflicts

    # Scalar fields use record-level LWW (newer timestamp wins)
    newer_ts = max(server_ts, client_ts)
    if client_ts > server_ts:
        scalar_risk_level = record.get("risk_level", existing.risk_level)
        scalar_risk_score = record.get("risk_score", existing.risk_score)
        scalar_risk_triggered = record.get("risk_triggered", existing.risk_triggered)
        scalar_gps_lat = record.get("gps_lat", existing.gps_lat)
        scalar_gps_lng = record.get("gps_lng", existing.gps_lng)
    else:
        scalar_risk_level = existing.risk_level
        scalar_risk_score = existing.risk_score
        scalar_risk_triggered = existing.risk_triggered
        scalar_gps_lat = existing.gps_lat
        scalar_gps_lng = existing.gps_lng

    await db.execute(
        update(Visit)
        .where(Visit.id == visit_id)
        .values(
            vitals=merged_vitals,
            observations=merged_obs,
            risk_level=scalar_risk_level,
            risk_score=scalar_risk_score,
            risk_triggered=scalar_risk_triggered,
            gps_lat=scalar_gps_lat,
            gps_lng=scalar_gps_lng,
            synced_at=_utc_now(),
            updated_at=newer_ts,
        )
    )

    # Log per-field conflicts for ANM review
    if all_field_conflicts:
        db.add(SyncConflict(
            entity_type="visit",
            entity_id=str(visit_id),
            device_id=device_id,
            client_payload=record,
            server_payload=_visit_to_dict(existing),
            resolved=False,
            conflict_ts=_utc_now(),
        ))
        return {
            "entity_id": visit_id,
            "reason": "field_level_merge",
            "fields_conflicted": len(all_field_conflicts),
            "details": all_field_conflicts,
        }

    return "updated"


# ---------------------------------------------------------------------------
# Patient upsert with field-level merge
# ---------------------------------------------------------------------------

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
            updated_at=client_ts,
        )
        db.add(patient)
        return "created"

    # Field-level LWW for patient demographics
    server_ts = (
        existing.updated_at.replace(tzinfo=timezone.utc)
        if existing.updated_at
        else datetime.min.replace(tzinfo=timezone.utc)
    )

    patient_fields = {
        "name": existing.name, "age": existing.age,
        "address": existing.address, "phone": existing.phone,
        "lmp": existing.lmp, "edd": existing.edd,
        "gravida": existing.gravida, "para": existing.para,
    }
    client_fields = {k: record.get(k) for k in patient_fields if k in record}
    merged, conflicts = field_level_merge(patient_fields, client_fields, server_ts, client_ts)

    existing.name = merged.get("name", existing.name)
    existing.age = merged.get("age", existing.age)
    existing.address = merged.get("address", existing.address)
    existing.phone = merged.get("phone", existing.phone)
    existing.lmp = merged.get("lmp", existing.lmp)
    existing.edd = merged.get("edd", existing.edd)
    existing.gravida = merged.get("gravida", existing.gravida)
    existing.para = merged.get("para", existing.para)
    existing.updated_at = max(server_ts, client_ts)

    if conflicts:
        db.add(SyncConflict(
            entity_type="patient",
            entity_id=str(patient_id),
            device_id=device_id,
            client_payload=record,
            server_payload={"id": existing.id, "name": existing.name,
                            "updated_at": server_ts.timestamp()},
            conflict_ts=_utc_now(),
        ))
        return {
            "entity_id": patient_id,
            "reason": "field_level_merge",
            "fields_conflicted": len(conflicts),
            "details": conflicts,
        }

    return "updated"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
