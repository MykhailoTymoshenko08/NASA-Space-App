"""A signed-in farmer's saved fields: create, list, get, update, delete, refresh the context snapshot.

Routes live under `/me/fields` because `/fields/{field_id}` is the public CSB lookup. Another user's
field (and a malformed id) is a plain 404, so ids cannot be probed.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from starlette.concurrency import run_in_threadpool

from app.auth.deps import get_current_user
from app.auth.store import User
from app.core.errors import ApiException, ErrorCode, not_found
from app.models import (
    FieldInfo,
    LatLon,
    Quality,
    SavedField,
    SavedFieldCreate,
    SavedFieldList,
    SavedFieldUpdate,
)
from app.saved_fields.geometry import place
from app.saved_fields.store import SavedFieldLimitReached, SavedFieldStore
from app.services import Services, get_services

log = logging.getLogger(__name__)
router = APIRouter(tags=["saved-fields"])


def get_saved_field_store(svc: Services = Depends(get_services)) -> SavedFieldStore:
    if svc.saved_fields is None:
        raise ApiException(ErrorCode.INTERNAL_ERROR, "Saved fields are unavailable (database not reachable).")
    return svc.saved_fields


def _id(raw: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError:
        raise _missing() from None


def _missing() -> ApiException:
    return not_found("Saved field not found.")


def _limit_reached(limit: int) -> ApiException:
    return ApiException(
        ErrorCode.FIELD_LIMIT_REACHED,
        f"You can save up to {limit} fields. Delete one to save another.",
        {"limit": limit},
    )


def _out(row: dict) -> SavedField:
    return SavedField(
        id=row["id"],
        name=row["name"],
        field_id=row["field_id"],
        geometry=row["geometry"],
        centroid=LatLon(lat=row["centroid_lat"], lon=row["centroid_lon"]),
        area_ha=row["area_ha"],
        state=row["state"].strip(),
        crop_history=row["crop_history"],
        info=row["info"],
        info_fetched_at=row["info_fetched_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _fetch_info(svc: Services, point: LatLon) -> FieldInfo | None:
    """Context for the centroid via the `/fields/info` service (bounded by SOURCE_TIMEOUT_S).

    None when it fails or every source is unavailable, so the snapshot can be refreshed later."""
    try:
        info = await svc.field_info.info(point)
    except Exception:  # noqa: BLE001 - saving the field matters more than its context
        log.warning("field info for saved field failed", exc_info=True)
        return None
    if all(m.quality == Quality.unavailable for m in info.metrics):
        return None
    return info


@router.post("/me/fields", status_code=201)
async def create_saved_field(
    body: SavedFieldCreate,
    response: Response,
    user: User = Depends(get_current_user),
    store: SavedFieldStore = Depends(get_saved_field_store),
    svc: Services = Depends(get_services),
) -> SavedField:
    placement = place(body.geometry, svc.boundaries_or_none)
    limit = svc.settings.saved_fields_max_per_user
    # Cheap early check so a full account does not wait for external data; `create` re-checks under a lock.
    if await run_in_threadpool(store.count, user.id) >= limit:
        raise _limit_reached(limit)
    info = await _fetch_info(svc, placement.centroid)
    try:
        row = await run_in_threadpool(
            lambda: store.create(
                user.id,
                limit=limit,
                name=body.name,
                field_id=body.field_id,
                geometry=placement.geometry,
                centroid_lat=placement.centroid.lat,
                centroid_lon=placement.centroid.lon,
                area_ha=placement.area_ha,
                state=placement.state,
                crop_history=[c.model_dump() for c in body.crop_history] if body.crop_history else None,
                info=info.model_dump(mode="json") if info else None,
                info_fetched_at=info.generated_at if info else None,
            )
        )
    except SavedFieldLimitReached:
        raise _limit_reached(limit) from None
    response.headers["Location"] = f"/v1/me/fields/{row['id']}"
    return _out(row)


@router.get("/me/fields")
def list_saved_fields(
    user: User = Depends(get_current_user),
    store: SavedFieldStore = Depends(get_saved_field_store),
    svc: Services = Depends(get_services),
) -> SavedFieldList:
    return SavedFieldList(
        items=[_out(r) for r in store.list(user.id)], limit=svc.settings.saved_fields_max_per_user
    )


@router.get("/me/fields/{saved_field_id}")
def get_saved_field(
    saved_field_id: str,
    user: User = Depends(get_current_user),
    store: SavedFieldStore = Depends(get_saved_field_store),
) -> SavedField:
    row = store.get(user.id, _id(saved_field_id))
    if row is None:
        raise _missing()
    return _out(row)


@router.patch("/me/fields/{saved_field_id}")
def update_saved_field(
    saved_field_id: str,
    body: SavedFieldUpdate,
    user: User = Depends(get_current_user),
    store: SavedFieldStore = Depends(get_saved_field_store),
) -> SavedField:
    changes = body.model_dump(include=body.model_fields_set)
    row = store.update(user.id, _id(saved_field_id), changes)
    if row is None:
        raise _missing()
    return _out(row)


@router.delete("/me/fields/{saved_field_id}", status_code=204)
def delete_saved_field(
    saved_field_id: str,
    user: User = Depends(get_current_user),
    store: SavedFieldStore = Depends(get_saved_field_store),
) -> Response:
    if not store.delete(user.id, _id(saved_field_id)):
        raise _missing()
    return Response(status_code=204)


@router.post("/me/fields/{saved_field_id}/refresh-info")
async def refresh_saved_field_info(
    saved_field_id: str,
    user: User = Depends(get_current_user),
    store: SavedFieldStore = Depends(get_saved_field_store),
    svc: Services = Depends(get_services),
) -> SavedField:
    fid = _id(saved_field_id)
    row = await run_in_threadpool(store.get, user.id, fid)
    if row is None:
        raise _missing()
    info = await _fetch_info(svc, LatLon(lat=row["centroid_lat"], lon=row["centroid_lon"]))
    if info is None:
        raise ApiException(
            ErrorCode.UPSTREAM_DATA_UNAVAILABLE,
            "Field data services are not answering right now. The previous snapshot is kept; "
            "try again shortly.",
        )
    changes = {"info": info.model_dump(mode="json"), "info_fetched_at": info.generated_at}
    row = await run_in_threadpool(store.update, user.id, fid, changes)
    if row is None:  # deleted while fetching
        raise _missing()
    return _out(row)
