from fastapi.testclient import TestClient

from tensordata.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "tensordata"


def test_api_is_closed_without_key(monkeypatch):
    monkeypatch.setenv("TENSORDATA_API_KEY", "")
    from tensordata.config import get_settings
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            create = client.post("/api/v1/assets", json={
                "name": "sample", "asset_type": "document", "owner": "test"
            })
            read = client.get("/api/v1/assets")
            assert create.status_code == 503
            assert read.status_code == 503
    finally:
        get_settings.cache_clear()


def test_asset_and_artifact_lifecycle(monkeypatch):
    monkeypatch.setenv("TENSORDATA_API_KEY", "test-secret")
    from tensordata.config import get_settings
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            headers = {"X-API-Key": "test-secret"}
            created = client.post("/api/v1/assets", headers=headers, json={
                "name": "ship motion sample",
                "asset_type": "timeseries",
                "owner": "tensor-physics",
                "rights_status": "approved",
                "allowed_purposes": ["research", "model_training"],
                "metadata": {"domain": "ship"}
            })
            assert created.status_code == 201
            asset = created.json()
            assert asset["lifecycle_state"] == "quarantine"

            listed = client.get("/api/v1/assets", headers=headers)
            assert listed.status_code == 200
            assert any(item["id"] == asset["id"] for item in listed.json())

            uploaded = client.post(
                f"/api/v1/assets/{asset['id']}/artifacts",
                headers=headers,
                files={"file": ("sample.csv", b"time,speed\n0,2.1\n1,2.4\n", "text/csv")},
            )
            assert uploaded.status_code == 201
            artifact = uploaded.json()
            assert artifact["asset_id"] == asset["id"]
            assert len(artifact["sha256"]) == 64
            assert artifact["size_bytes"] > 0
    finally:
        get_settings.cache_clear()
