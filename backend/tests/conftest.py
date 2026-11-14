import os

import pytest
from fastapi.testclient import TestClient

# Tests never touch the network or the real data dir.
os.environ.setdefault("STUB_DURATION_S", "0")

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests import fixture_data  # noqa: E402
from tests.contract import BASE_URL  # noqa: E402


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    return fixture_data.build(tmp_path_factory.mktemp("data"))


@pytest.fixture(scope="session")
def empty_data_dir(tmp_path_factory):
    """Boundaries only, no field data: everything resolves to buffered points."""
    return fixture_data.build(tmp_path_factory.mktemp("data_nofields"), with_fields=False)


def make_settings(data_dir, tmp_path, **kw) -> Settings:
    base = dict(
        data_dir=data_dir,
        cache_dir=tmp_path / "cache",
        stub_duration_s=0,
        log_level="WARNING",
    )
    return Settings(**{**base, **kw})


@pytest.fixture
def settings(data_dir, tmp_path) -> Settings:
    return make_settings(data_dir, tmp_path)


@pytest.fixture
def client(settings) -> TestClient:
    with TestClient(create_app(settings), base_url=BASE_URL) as c:
        yield c


@pytest.fixture
def make_client(tmp_path):
    """Build a client with custom settings: `make_client(data_dir, stub_fail_rate=1.0)`."""
    clients = []

    def _make(data_dir, **kw):
        c = TestClient(create_app(make_settings(data_dir, tmp_path, **kw)), base_url=BASE_URL)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)
