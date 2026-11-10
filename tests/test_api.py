from fastapi.testclient import TestClient

from tensordata.main import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "tensordata"


def test_write_requires_configured_key(monkeypatch):
    monkeypatch.setenv("TENSORDATA_API_KEY", "")
    from tensordata.config import get_settings
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/assets", json={
                "name": "sample", "asset_type": "document", "owner": "test"
            })
            assert response.status_code == 503
    finally:
        get_settings.cache_clear()
