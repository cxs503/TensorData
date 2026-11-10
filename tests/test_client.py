import httpx
import pytest

from tensordata.client import TensorDataAPIError, TensorDataClient


def test_agent_client_runs_asset_quality_dataset_and_lineage_flow():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/assets":
            return httpx.Response(201, json={"id": "asset-1"})
        if path == "/api/v1/assets/asset-1/artifacts":
            assert b"ship.csv" in request.read()
            return httpx.Response(201, json={"id": "artifact-1"})
        if path == "/api/v1/artifacts/artifact-1/quality-checks":
            return httpx.Response(201, json={"id": "quality-1", "status": "passed"})
        if path == "/api/v1/datasets":
            return httpx.Response(201, json={"id": "dataset-1"})
        if path == "/api/v1/datasets/dataset-1/versions":
            return httpx.Response(201, json={"version": "1.0.0"})
        if path == "/api/v1/lineage/artifacts/artifact-1":
            return httpx.Response(200, json={"target_artifact_id": "artifact-1"})
        return httpx.Response(404, json={"detail": "not found"})

    with TensorDataClient(
        "https://tensordata.example",
        "agent-key",
        transport=httpx.MockTransport(handler),
    ) as client:
        asset = client.create_asset({"name": "ship motion", "asset_type": "table", "owner": "agent"})
        artifact = client.upload_artifact(
            asset["id"], "ship.csv", b"time,speed\n0,2.1\n", media_type="text/csv"
        )
        report = client.run_quality_checks(
            artifact["id"], profile="tabular", executed_by="ship-agent"
        )
        dataset = client.create_dataset({"name": "ship-train", "owner": "agent"})
        version = client.create_dataset_version(
            dataset["id"],
            {
                "version": "1.0.0",
                "members": [{"artifact_id": artifact["id"]}],
                "created_by": "ship-agent",
            },
        )
        lineage = client.get_artifact_lineage(artifact["id"])

    assert report["status"] == "passed"
    assert version["version"] == "1.0.0"
    assert lineage["target_artifact_id"] == "artifact-1"
    assert all(request.headers["x-api-key"] == "agent-key" for request in requests)


def test_agent_client_exposes_structured_api_errors():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "quality report required"})

    with TensorDataClient(
        "https://tensordata.example",
        "agent-key",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(TensorDataAPIError) as error:
            client.create_dataset_version("dataset-1", {"version": "1.0.0"})

    assert error.value.status_code == 422
    assert error.value.detail == "quality report required"
