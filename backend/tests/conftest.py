import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

# Tests never touch the network or the real data dir.
os.environ.setdefault("STUB_DURATION_S", "0")

# PostGIS server for a scratch database (created and dropped per session). `make db` starts one.
TEST_DB_ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL", "postgresql://fieldshift:fieldshift@localhost:5433/postgres"
)

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests import fixture_data  # noqa: E402
from tests.contract import BASE_URL  # noqa: E402


@pytest.fixture(scope="session")
def db_url():
    """URL of a fresh PostGIS database holding the fixture fields; dropped after the session."""
    name = f"fieldshift_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(TEST_DB_ADMIN_URL, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        pytest.exit(f"PostGIS not reachable at {TEST_DB_ADMIN_URL} ({e}). Run `make db` first.", 2)
    admin.execute(f'CREATE DATABASE "{name}"')
    url = TEST_DB_ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(url, autocommit=True) as c:
        fixture_data.load_fields(c)
    yield url
    admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    return fixture_data.build(tmp_path_factory.mktemp("data"))


def make_settings(data_dir, tmp_path, **kw) -> Settings:
    base = dict(
        data_dir=data_dir,
        cache_dir=tmp_path / "cache",
        stub_duration_s=0,
        log_level="WARNING",
        database_url="",
        analysis_engine="stub",
    )
    return Settings(**{**base, **kw})


@pytest.fixture
def settings(data_dir, db_url, tmp_path) -> Settings:
    return make_settings(data_dir, tmp_path, database_url=db_url)


@pytest.fixture
def client(settings) -> TestClient:
    with TestClient(create_app(settings), base_url=BASE_URL) as c:
        yield c


@pytest.fixture
def make_client(tmp_path, db_url):
    """Build a client with custom settings: `make_client(data_dir, stub_fail_rate=1.0)`.

    Uses the fixture fields; `database_url=""` gives a server without field polygons."""
    clients = []

    def _make(data_dir, **kw):
        kw.setdefault("database_url", db_url)
        c = TestClient(create_app(make_settings(data_dir, tmp_path, **kw)), base_url=BASE_URL)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)
