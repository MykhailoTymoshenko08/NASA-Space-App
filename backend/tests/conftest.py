import os

import pytest
from fastapi.testclient import TestClient

# Tests never touch the network or real data dirs unless a fixture opts in.
os.environ.setdefault("STUB_DURATION_S", "0")

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.contract import BASE_URL  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", stub_duration_s=0, log_level="WARNING")


@pytest.fixture
def client(settings) -> TestClient:
    with TestClient(create_app(settings), base_url=BASE_URL) as c:
        yield c
