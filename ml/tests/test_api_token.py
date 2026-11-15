"""ML_API_TOKEN: /ml/v1/* needs X-ML-Token, /ml/health stays open."""
from fastapi.testclient import TestClient

from ml_service.main import app


def test_token_required_when_set(monkeypatch):
    monkeypatch.setenv("ML_MODE", "mock")
    monkeypatch.setenv("ML_API_TOKEN", "s3cret")
    with TestClient(app) as client:
        assert client.get("/ml/health").status_code == 200
        r = client.get("/ml/v1/meta/crops")
        assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
        assert client.get("/ml/v1/meta/crops", headers={"X-ML-Token": "wrong"}).status_code == 401
        assert client.get("/ml/v1/meta/crops", headers={"X-ML-Token": "s3cret"}).status_code == 200


def test_open_without_token(monkeypatch):
    monkeypatch.setenv("ML_MODE", "mock")
    monkeypatch.delenv("ML_API_TOKEN", raising=False)
    with TestClient(app) as client:
        assert client.get("/ml/v1/meta/crops").status_code == 200
