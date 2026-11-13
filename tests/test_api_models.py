"""HTTP surface of the model registry: register -> list -> verify -> predict."""

from __future__ import annotations

import json
import numpy as np
import pytest
from fastapi.testclient import TestClient

from tensordata.main import app
from tensordata.modelreg import sha256_file
from tests.test_modelreg import make_model


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TENSORDATA_API_KEY", "test-secret")
    monkeypatch.setenv("TENSORDATA_MODEL_REGISTRY_ROOT", str(tmp_path / "registry"))
    monkeypatch.setenv("TENSORDATA_DATABASE_URL", f"sqlite:///{tmp_path}/api.db")
    monkeypatch.setenv("TENSORDATA_STORAGE_ROOT", str(tmp_path / "artifacts"))
    from tensordata.config import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


HEADERS = {"X-API-Key": "test-secret"}


def _register(client, fixture):
    # one multipart entry per payload, filename = manifest-relative path
    multipart = [
        ("manifest", (None, json.dumps(fixture["manifest"]), "application/json")),
        ("artifacts", ("weights/weights.npz", fixture["weights"].read_bytes(),
                       "application/octet-stream")),
        ("artifacts", ("eval_card.json", (fixture["work"] / "eval_card.json").read_bytes(),
                       "application/json")),
        ("artifacts", ("training_table.npz", fixture["table"].read_bytes(),
                       "application/octet-stream")),
    ]
    return client.post("/api/v1/models", headers=HEADERS, files=multipart)


def test_models_endpoints_require_key(client):
    assert client.get("/api/v1/models").status_code == 401
    assert client.get("/api/v1/models", headers={"X-API-Key": "wrong"}).status_code == 401


def test_model_lifecycle_over_http(tmp_path, client):
    fixture = make_model(tmp_path, seed=31)

    created = _register(client, fixture)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["model_id"] == "synthetic-affine"
    assert body["weights_sha256"] == sha256_file(fixture["weights"])
    assert body["data_fingerprint"].startswith("sha256:")

    listed = client.get("/api/v1/models", headers=HEADERS)
    assert listed.status_code == 200
    assert [r["model_id"] for r in listed.json()] == ["synthetic-affine"]

    versions = client.get("/api/v1/models/synthetic-affine/versions", headers=HEADERS)
    assert versions.json() == {"model_id": "synthetic-affine", "versions": ["0.1.0"]}

    manifest = client.get("/api/v1/models/synthetic-affine", headers=HEADERS)
    assert manifest.status_code == 200
    assert manifest.json()["manifest_sha256"] == body["manifest_sha256"]

    verified = client.get("/api/v1/models/synthetic-affine/verify", headers=HEADERS)
    assert verified.status_code == 200, verified.text
    assert verified.json()["ok"] is True

    predicted = client.post("/api/v1/models/synthetic-affine/predict", headers=HEADERS,
                            json={"inputs": fixture["X"][:2].astype(float).tolist()})
    assert predicted.status_code == 200, predicted.text
    payload = predicted.json()
    expected = fixture["X"][:2].astype(float) @ fixture["W"].T + fixture["b"]
    assert np.allclose(np.asarray(payload["outputs"]), expected, atol=1e-9)
    assert payload["out_of_domain"]["n_out_of_domain"] == 0

    # duplicate version over HTTP is a conflict, not a 500
    assert _register(client, fixture).status_code == 409


def test_model_api_rejects_bad_inputs(tmp_path, client):
    fixture = make_model(tmp_path, seed=32)
    broken = json.loads(json.dumps(fixture["manifest"]))
    broken["model_id"] = "Not a Slug"
    bad_manifest = [
        ("manifest", (None, json.dumps(broken), "application/json")),
        ("artifacts", ("weights/weights.npz", fixture["weights"].read_bytes(), "application/octet-stream")),
    ]
    assert client.post("/api/v1/models", headers=HEADERS, files=bad_manifest).status_code == 422

    assert client.post("/api/v1/models", headers=HEADERS,
                       files=[("manifest", (None, "{not json", "application/json"))]).status_code == 422

    assert client.get("/api/v1/models/unknown-model", headers=HEADERS).status_code == 404
    assert client.get("/api/v1/models/unknown-model/versions", headers=HEADERS).status_code == 404

    _register(client, fixture)
    # 422: wrong input width, 422: missing inputs key
    assert client.post("/api/v1/models/synthetic-affine/predict", headers=HEADERS,
                       json={"inputs": [[0.0, 0.0]]}).status_code == 422
    assert client.post("/api/v1/models/synthetic-affine/predict", headers=HEADERS,
                       json={}).status_code == 422


def test_model_api_detects_tampering(tmp_path, client):
    fixture = make_model(tmp_path, seed=33)
    assert _register(client, fixture).status_code == 201
    tampered = tmp_path / "registry/synthetic-affine/0.1.0/weights/weights.npz"
    tampered.write_bytes(b"not the registered weights")
    response = client.get("/api/v1/models/synthetic-affine/verify", headers=HEADERS)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["ok"] is False