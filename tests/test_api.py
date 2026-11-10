from uuid import uuid4

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


def test_asset_dataset_version_and_provenance_lifecycle(monkeypatch):
    monkeypatch.setenv("TENSORDATA_API_KEY", "test-secret")
    from tensordata.config import get_settings
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            headers = {"X-API-Key": "test-secret"}
            created = client.post("/api/v1/assets", headers=headers, json={
                "name": f"ship motion sample {uuid4()}",
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

            dataset_response = client.post("/api/v1/datasets", headers=headers, json={
                "name": f"ship-motion-training-{uuid4()}",
                "description": "Initial ship motion dataset",
                "owner": "tensor-physics",
                "intended_uses": ["research", "model_training"],
            })
            assert dataset_response.status_code == 201
            dataset = dataset_response.json()

            version_payload = {
                "version": "1.0.0",
                "members": [{"artifact_id": artifact["id"], "role": "observations"}],
                "split_definition": {"strategy": "not_yet_split"},
                "schema_refs": ["ship-motion-timeseries/v1"],
                "transform_refs": [],
                "created_by": "test-agent",
            }
            version_response = client.post(
                f"/api/v1/datasets/{dataset['id']}/versions",
                headers=headers,
                json=version_payload,
            )
            assert version_response.status_code == 201
            version = version_response.json()
            assert len(version["manifest_sha256"]) == 64
            assert version["manifest_json"]["members"][0]["artifact_sha256"] == artifact["sha256"]
            assert version["manifest_json"]["members"][0]["rights_status_at_snapshot"] == "review_required"
            assert version["manifest_json"]["members"][0]["lifecycle_state_at_snapshot"] == "quarantine"

            prohibited_asset_response = client.post("/api/v1/assets", headers=headers, json={
                "name": f"restricted ship source {uuid4()}",
                "asset_type": "document",
                "owner": "external-source",
                "rights_status": "prohibited",
            })
            assert prohibited_asset_response.status_code == 201
            prohibited_asset = prohibited_asset_response.json()
            prohibited_upload = client.post(
                f"/api/v1/assets/{prohibited_asset['id']}/artifacts",
                headers=headers,
                files={"file": ("prohibited.txt", b"do not redistribute", "text/plain")},
            )
            assert prohibited_upload.status_code == 201
            prohibited_version = client.post(
                f"/api/v1/datasets/{dataset['id']}/versions",
                headers=headers,
                json={
                    **version_payload,
                    "version": "1.0.1",
                    "members": [
                        {"artifact_id": artifact["id"]},
                        {"artifact_id": prohibited_upload.json()["id"]},
                    ],
                },
            )
            assert prohibited_version.status_code == 422

            duplicate_version = client.post(
                f"/api/v1/datasets/{dataset['id']}/versions",
                headers=headers,
                json=version_payload,
            )
            assert duplicate_version.status_code == 409

            unknown_artifact = client.post(
                f"/api/v1/datasets/{dataset['id']}/versions",
                headers=headers,
                json={
                    **version_payload,
                    "version": "1.0.1",
                    "members": [{"artifact_id": str(uuid4())}],
                },
            )
            assert unknown_artifact.status_code == 422

            listed_versions = client.get(
                f"/api/v1/datasets/{dataset['id']}/versions",
                headers=headers,
            )
            assert listed_versions.status_code == 200
            assert [item["version"] for item in listed_versions.json()] == ["1.0.0"]

            provenance_response = client.post("/api/v1/provenance", headers=headers, json={
                "activity_type": "csv_ingestion",
                "inputs": [{"uri": "source://ship/sensor-01"}],
                "outputs": [{"artifact_id": artifact["id"], "sha256": artifact["sha256"]}],
                "parameters": {"parser": "csv", "encoding": "utf-8"},
                "responsible_actor": "tensor-data-agent",
                "code_digest": "git:abc123",
                "environment_digest": "container:sha256-example",
            })
            assert provenance_response.status_code == 201
            provenance = provenance_response.json()
            assert provenance["outputs_json"][0]["artifact_id"] == artifact["id"]

            provenance_list = client.get(
                "/api/v1/provenance?activity_type=csv_ingestion",
                headers=headers,
            )
            assert provenance_list.status_code == 200
            assert any(item["id"] == provenance["id"] for item in provenance_list.json())
    finally:
        get_settings.cache_clear()
