from fastapi import APIRouter, Depends

from app.geo.resolve import resolve_ref
from app.models import Snapshot, SnapshotRequest
from app.services import Services, get_services

router = APIRouter(tags=["snapshots"])


@router.post("/snapshots")
async def create_snapshot(body: SnapshotRequest, svc: Services = Depends(get_services)) -> Snapshot:
    selection = resolve_ref(svc, body.selection)
    return await svc.snapshots.snapshot(selection)
