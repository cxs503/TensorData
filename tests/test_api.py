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
                "rights_status": "review_required",
                "allowed_purposes": ["research"],
                "metadata": {"domain": "ship"}
            })
            assert created.status_code == 201
            asset = created.json()
            assert asset["lifecycle_state"] == "quarantine"
            assert asset["rights_status"] == "review_required"

            rejected_self_approval = client.post("/api/v1/assets", headers=headers, json={
                "name": "self-approved sample",
                "asset_type": "document",
                "owner": "untrusted-producer",
                "rights_status": "approved"
            })
            assert rejected_self_approval.status_code == 422

            listed = client.get("/api/v1/assets", headers=headers)
            assert listed.status_code == 200
            assert any(item["id"] == asset["id"] for item in listed.json())

            payload = b"time,speed\n0,2.1\n1,2.4\n"
            uploaded = client.post(
                f"/api/v1/assets/{asset['id']}/artifacts",
                headers=headers,
                files={"file": ("sample.csv", payload, "text/csv")},
            )
            assert uploaded.status_code == 201
            artifact = uploaded.json()
            assert artifact["asset_id"] == asset["id"]
            assert len(artifact["sha256"]) == 64
            assert artifact["size_bytes"] == len(payload)

            repeated = client.post(
                f"/api/v1/assets/{asset['id']}/artifacts",
                headers=headers,
                files={"file": ("renamed.csv", payload, "text/csv")},
            )
            assert repeated.status_code == 201
            assert repeated.json()["id"] == artifact["id"]

            downloaded = client.get(
                f"/api/v1/artifacts/{artifact['id']}/content",
                headers=headers,
            )
            assert downloaded.status_code == 200
            assert downloaded.content == payload
            assert downloaded.headers["x-content-sha256"] == artifact["sha256"]
    finally:
        get_settings.cache_clear()
