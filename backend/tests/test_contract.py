"""Contract tests: real responses of every endpoint validated against contract/openapi.yaml.

Run alone with `make contract-check`. Endpoint-specific fixtures live in conftest.py.
"""

import httpx
import pytest

from tests.contract import BASE_URL, assert_matches_contract

pytestmark = pytest.mark.contract


def test_validator_rejects_drift():
    """Guard: the harness must actually catch a shape the YAML does not describe."""
    req = httpx.Request("GET", f"{BASE_URL}/v1/health")
    bad = httpx.Response(
        200, json={"status": "fine"}, headers={"X-Request-Id": "x"}, request=req
    )
    with pytest.raises(Exception):  # noqa: B017
        assert_matches_contract(bad)


def test_health(client):
    assert_matches_contract(client.get("/v1/health"))
