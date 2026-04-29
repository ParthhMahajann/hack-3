from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User
from backend.schemas import SyncPayload, SyncResponse
from backend.routers.auth import get_current_user
from backend.core.sync_engine import process_sync_payload

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/", response_model=SyncResponse)
async def sync(
    payload: SyncPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Bidirectional sync endpoint.
    Client pushes queued offline records; server returns changes since last_sync_ts.
    Critical (RED/PURPLE) records are processed before routine ones.
    """
    result = await process_sync_payload(
        device_id=payload.device_id,
        last_sync_ts=payload.last_sync_ts,
        incoming_records=payload.records,
        db=db,
    )
    return SyncResponse(
        status=result["status"],
        created=result["created"],
        updated=result["updated"],
        conflicts=result["conflicts"],
        server_changes=result["server_changes"],
        server_ts=result["server_ts"],
    )
