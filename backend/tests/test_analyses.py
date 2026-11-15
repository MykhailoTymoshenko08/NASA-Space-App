"""M5: analysis job lifecycle, stub engine, failure switch. Upstreams mocked (see test_snapshots)."""

import time

import pytest
import respx

from tests.contract import assert_matches_contract
from tests.test_auth import SECRET, bearer, register
from tests.test_snapshots import mock_all

pytestmark = pytest.mark.contract

F1 = {"field_id": "csb2025_190000000001"}
F2 = {"field_id": "csb2025_190000000002"}


def wait_done(client, job_id, timeout=5.0, headers=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/v1/analyses/{job_id}", headers=headers)
        assert_matches_contract(r)
        if r.json()["status"] in ("succeeded", "failed"):
            return r
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def run(client, body, headers=None):
    with respx.mock(assert_all_called=False) as router:
        mock_all(router)
        r = client.post("/v1/analyses", json=body, headers=headers)
        assert r.status_code == 202, r.text
        assert_matches_contract(r)
        done = wait_done(client, r.json()["job_id"], headers=headers)
    return r, done


def test_create_returns_202_queued_with_location(client):
    r, _ = run(client, {"selection": F1})
    job = r.json()
    assert job["status"] in ("queued", "running")
    assert r.headers["location"] == f"/v1/analyses/{job['job_id']}"
    assert "result" not in job and "error" not in job
    assert 0 <= job["progress"]["percent"] <= 100 and job["progress"]["stage"]


def test_job_succeeds_with_full_result(client):
    _, done = run(client, {"selection": F1, "options": {"priorities": ["soil_health"]}})
    job = done.json()
    assert job["status"] == "succeeded"
    assert job["progress"] == {"percent": 100, "stage": "Done"}
    assert job["finished_at"]
    assert "error" not in job
    res = job["result"]
    assert res["model_version"] == "stub-0"
    assert "Demo results: placeholder strategies, real model not connected yet." in res["warnings"]
    assert "local" in res["disclaimer"]
    assert res["current_conditions"] and res["datasets_used"]
    strats = res["strategies"]
    assert len(strats) >= 3
    assert sum(s["is_current"] for s in strats) == 1
    scores = [s["score"] for s in strats]
    assert scores == sorted(scores, reverse=True)
    for s in strats:
        assert s["confidence"] == "low" and s["needs_local_review"] is True
        for k in ("rotation", "score_breakdown", "benefits", "risks", "evidence", "information_gaps"):
            assert s[k], k
    current = next(s for s in strats if s["is_current"])
    # F1's CSB-mapped history (2023 Corn, 2024 Soybeans, 2025 Corn) is the baseline.
    assert current["name"] == "Continue current rotation: Corn / Soybeans"
    assert "No crop history provided" not in current["information_gaps"]


def test_baseline_without_history_uses_generic(client):
    _, done = run(client, {"selection": F2})
    strats = done.json()["result"]["strategies"]
    current = next(s for s in strats if s["is_current"])
    assert current["name"] == "Continue current practice (crops unknown)"
    for s in strats:
        assert "No crop history provided" in s["information_gaps"]


def test_farmer_crop_history_used_for_baseline(client):
    body = {"selection": F2, "options": {"crop_history": [
        {"year": 2024, "crop": "Oats"}, {"year": 2023, "crop": "Alfalfa"}]}}
    _, done = run(client, body)
    current = next(s for s in done.json()["result"]["strategies"] if s["is_current"])
    assert [x["crop"] for x in current["rotation"]] == ["Alfalfa", "Oats"]
    assert "No crop history provided" not in current["information_gaps"]


def test_farmer_history_overrides_mapped_history(client):
    body = {"selection": F1, "options": {"crop_history": [{"year": 2025, "crop": "Oats"}]}}
    _, done = run(client, body)
    current = next(s for s in done.json()["result"]["strategies"] if s["is_current"])
    assert [x["crop"] for x in current["rotation"]] == ["Oats"]


def test_deterministic_per_field(make_client, data_dir):
    a = make_client(data_dir)
    b = make_client(data_dir)
    _, ra = run(a, {"selection": F1})
    _, rb = run(b, {"selection": F1})
    sa = [(s["id"], s["score"]) for s in ra.json()["result"]["strategies"]]
    sb = [(s["id"], s["score"]) for s in rb.json()["result"]["strategies"]]
    assert sa == sb


def test_identical_request_reuses_job(client):
    r1, _ = run(client, {"selection": F1})
    r2, _ = run(client, {"selection": F1})
    assert r1.json()["job_id"] == r2.json()["job_id"]
    r3, _ = run(client, {"selection": F1, "options": {"horizon_years": 5}})
    assert r3.json()["job_id"] != r1.json()["job_id"]


def test_private_jobs_and_deduplication_are_scoped_to_the_owner(client):
    alice = register(client)
    bob = register(client)
    assert alice.status_code == bob.status_code == 201
    alice_auth, bob_auth = bearer(alice.json()["access_token"]), bearer(bob.json()["access_token"])
    body = {"selection": F1, "options": {"horizon_years": 4}}
    alice_created, _ = run(client, body, headers=alice_auth)
    bob_created, _ = run(client, body, headers=bob_auth)
    guest_created, _ = run(client, body)
    job_id = alice_created.json()["job_id"]
    assert len({job_id, bob_created.json()["job_id"], guest_created.json()["job_id"]}) == 3
    repeated, _ = run(client, body, headers=alice_auth)
    assert repeated.json()["job_id"] == job_id
    for headers in (None, bob_auth):
        hidden = client.get(f"/v1/analyses/{job_id}", headers=headers)
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "NOT_FOUND"
        assert_matches_contract(hidden)
    owner = client.get(f"/v1/analyses/{job_id}", headers=alice_auth)
    assert owner.status_code == 200 and owner.json()["status"] == "succeeded"
    assert_matches_contract(owner)


def test_jobs_echo_the_original_options_without_url_parameters(client):
    options = {
        "priorities": ["soil_health", "erosion_control"],
        "crop_history": [{"year": 2025, "crop": "Oats"}],
        "horizon_years": 5,
        "irrigated": True, "has_livestock": False,
        "budget": {"land_rent_per_acre": 0, "cover_cost_per_acre": 42, "crop_overrides": []},
    }
    created, done = run(client, {"selection": F1, "options": options})
    assert created.json()["options"] == options
    assert done.json()["options"] == options
    # A result URL may carry arbitrary display parameters; they must never alter server-owned choices.
    retrieved = client.get(f"/v1/analyses/{created.json()['job_id']}?h=1&p=extra_income")
    assert retrieved.status_code == 200 and retrieved.json()["options"] == options
    assert_matches_contract(retrieved)


def test_finished_private_job_is_shared_by_independent_database_workers(make_client, data_dir):
    first = make_client(data_dir, state_backend="auto", jwt_secret=SECRET)
    second = make_client(data_dir, state_backend="auto", jwt_secret=SECRET)
    account = register(first)
    assert account.status_code == 201
    headers = bearer(account.json()["access_token"])
    body = {"selection": F1, "options": {"horizon_years": 5, "priorities": ["water_conservation"]}}
    created, done = run(first, body, headers=headers)
    other = second.get(f"/v1/analyses/{created.json()['job_id']}", headers=headers)
    assert other.status_code == 200
    assert_matches_contract(other)
    assert other.json() == done.json()
    assert other.json()["options"]["horizon_years"] == 5
    assert other.json()["options"]["priorities"] == ["water_conservation"]
    assert first.app.state.services.analyses.store is not second.app.state.services.analyses.store


def test_point_selection_buffered(client):
    _, done = run(client, {"selection": {"point": {"lat": 41.70, "lon": -93.70}}})
    res = done.json()["result"]
    assert res["selection"]["resolved_by"] == "buffered_point"
    assert any("500 m" in w for w in res["warnings"])


def test_failure_switch(make_client, data_dir):
    c = make_client(data_dir, stub_fail_rate=1.0)
    _, done = run(c, {"selection": F1})
    job = done.json()
    assert done.status_code == 200  # a failed JOB is still HTTP 200
    assert job["status"] == "failed"
    assert job["error"]["code"] == "INTERNAL_ERROR" and job["error"]["message"]
    assert "result" not in job


def test_failed_job_is_not_reused(make_client, data_dir):
    c = make_client(data_dir, stub_fail_rate=1.0)
    r1, _ = run(c, {"selection": F1})
    r2, _ = run(c, {"selection": F1})
    assert r1.json()["job_id"] != r2.json()["job_id"]


@pytest.mark.parametrize("job_id", ["7d3c5a2e-0000-4000-8000-000000000000", "not-a-uuid"])
def test_unknown_job_404(client, job_id):
    r = client.get(f"/v1/analyses/{job_id}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_unknown_field_404(client):
    r = client.post("/v1/analyses", json={"selection": {"field_id": "fld_nope000000"}})
    assert r.status_code == 404
    assert_matches_contract(r)


def test_outside_coverage_422(client):
    r = client.post("/v1/analyses", json={"selection": {"point": {"lat": 48.85, "lon": 2.35}}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "OUTSIDE_COVERAGE"
    assert_matches_contract(r)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"selection": F1, "options": {"priorities": ["world_peace"]}},
        {"selection": F1, "options": {"horizon_years": 9}},
        {"selection": F1, "options": {"crop_history": [{"year": 1800, "crop": "Corn"}]}},
    ],
)
def test_validation(client, body):
    r = client.post("/v1/analyses", json=body)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_matches_contract(r)


def test_progress_visible_while_running(make_client, data_dir):
    c = make_client(data_dir, stub_duration_s=0.5)
    with respx.mock(assert_all_called=False) as router:
        mock_all(router)
        job_id = c.post("/v1/analyses", json={"selection": F1}).json()["job_id"]
        time.sleep(0.2)
        mid = c.get(f"/v1/analyses/{job_id}")
        assert_matches_contract(mid)
        j = mid.json()
        assert j["status"] == "running" and 0 < j["progress"]["percent"] < 100
        assert "result" not in j
        wait_done(c, job_id)
