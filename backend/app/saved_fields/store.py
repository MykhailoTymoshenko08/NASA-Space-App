"""Saved fields in PostgreSQL (the same database and pool as the users table).

No migration tool in this project: the table is created on startup if missing, like `users`.
  saved_fields(id uuid PK, user_id FK users ON DELETE CASCADE, name, field_id (CSB id or null),
               geometry jsonb (GeoJSON Point or Polygon), centroid_lat/lon, area_ha (null for points),
               state ('IA'|'IL'|'NE'), crop_history jsonb (farmer-entered, nullable),
               info jsonb (FieldInfo snapshot, nullable), info_fetched_at, created_at, updated_at)

Every query filters on user_id, so one user can never read, change or delete another user's field.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS saved_fields (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            text NOT NULL,
    field_id        text,
    geometry        jsonb NOT NULL,
    centroid_lat    double precision NOT NULL,
    centroid_lon    double precision NOT NULL,
    area_ha         double precision,
    state           char(2) NOT NULL,
    crop_history    jsonb,
    info            jsonb,
    info_fetched_at timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS saved_fields_user_idx ON saved_fields (user_id, created_at DESC);
"""

_COLS = (
    "id, name, field_id, geometry, centroid_lat, centroid_lon, area_ha, state, crop_history, info,"
    " info_fetched_at, created_at, updated_at"
)


class SavedFieldLimitReached(Exception):
    pass


def _json(v: Any) -> Jsonb | None:
    return None if v is None else Jsonb(v)


class SavedFieldStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    @classmethod
    def attach(cls, pool: ConnectionPool) -> "SavedFieldStore":
        """Use an open pool whose database already has `users`; create the table if missing."""
        with pool.connection() as c:
            c.execute(SCHEMA_SQL)
        return cls(pool)

    def count(self, user_id: UUID) -> int:
        with self._pool.connection() as c:
            return c.execute(
                "SELECT count(*) AS n FROM saved_fields WHERE user_id = %s", (user_id,)
            ).fetchone()["n"]

    def create(
        self,
        user_id: UUID,
        *,
        limit: int,
        name: str,
        field_id: str | None,
        geometry: dict,
        centroid_lat: float,
        centroid_lon: float,
        area_ha: float | None,
        state: str,
        crop_history: list[dict] | None,
        info: dict | None,
        info_fetched_at: datetime | None,
    ) -> dict:
        with self._pool.connection() as c, c.transaction():
            # Lock the user's row so two concurrent creates cannot both pass the limit check.
            c.execute("SELECT 1 FROM users WHERE id = %s FOR UPDATE", (user_id,))
            n = c.execute("SELECT count(*) AS n FROM saved_fields WHERE user_id = %s", (user_id,)).fetchone()
            if n["n"] >= limit:
                raise SavedFieldLimitReached(limit)
            return c.execute(
                f"""INSERT INTO saved_fields (user_id, name, field_id, geometry, centroid_lat, centroid_lon,
                        area_ha, state, crop_history, info, info_fetched_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {_COLS}""",
                (user_id, name, field_id, Jsonb(geometry), centroid_lat, centroid_lon, area_ha, state,
                 _json(crop_history), _json(info), info_fetched_at),
            ).fetchone()

    def list(self, user_id: UUID) -> list[dict]:
        with self._pool.connection() as c:
            return c.execute(
                f"SELECT {_COLS} FROM saved_fields WHERE user_id = %s ORDER BY created_at DESC, id",
                (user_id,),
            ).fetchall()

    def get(self, user_id: UUID, field_id: UUID) -> dict | None:
        with self._pool.connection() as c:
            return c.execute(
                f"SELECT {_COLS} FROM saved_fields WHERE user_id = %s AND id = %s", (user_id, field_id)
            ).fetchone()

    def update(self, user_id: UUID, field_id: UUID, changes: dict[str, Any]) -> dict | None:
        """Apply `changes` (keys: name, crop_history, info, info_fetched_at). None if not this user's."""
        allowed = {"name", "crop_history", "info", "info_fetched_at"}
        if not changes.keys() <= allowed:
            raise ValueError(f"cannot update {sorted(changes.keys() - allowed)}")
        sets = ["updated_at = now()"]
        params: list[Any] = []
        for key, value in changes.items():
            sets.append(f"{key} = %s")
            params.append(_json(value) if key in {"crop_history", "info"} else value)
        with self._pool.connection() as c:
            return c.execute(
                f"UPDATE saved_fields SET {', '.join(sets)} WHERE user_id = %s AND id = %s RETURNING {_COLS}",
                (*params, user_id, field_id),
            ).fetchone()

    def delete(self, user_id: UUID, field_id: UUID) -> bool:
        with self._pool.connection() as c:
            cur = c.execute("DELETE FROM saved_fields WHERE user_id = %s AND id = %s", (user_id, field_id))
            return cur.rowcount == 1
