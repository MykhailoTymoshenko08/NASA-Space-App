"""Connection pools for DATABASE_URL.

Hosted serverless Postgres (Neon) suspends its compute when idle and drops open connections, and an idle
connection may keep it from suspending. So pools keep no connections while idle (min_size=0, closed after
max_idle seconds) and test each connection before handing it out (one round trip), replacing dead ones.
"""

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MAX_IDLE_S = 120.0


def open_pool(url: str, max_size: int) -> ConnectionPool:
    """A closed pool: the caller opens it (`pool.open(wait=True, timeout=...)`)."""
    return ConnectionPool(
        url, min_size=0, max_size=max_size, max_idle=MAX_IDLE_S, open=False,
        check=ConnectionPool.check_connection, kwargs={"row_factory": dict_row},
    )
