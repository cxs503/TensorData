"""Reliability tests for the quality engine and its API integration.

Every check here executes the real engine against real payloads on disk and a
real app + database — nothing mocks check execution to fabricate a pass. The
memory test asserts actual tracemalloc peaks, and the rule-crash test injects
a genuine fault to prove a broken rule can never masquerade as a pass.
"""

import tracemalloc
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient

from tensordata.main import QUALITY_ENGINE, app


def make_client(monkeypatch, tmp_path, api_key: str = "quality-reliability") -> TestClient:
    """Per-test key plus an isolated storage root.

    The tamper tests rewrite payload bytes under the storage root; giving each
    test its own root keeps the shared content-addressed tree pristine and the
    suite idempotent across re-runs.
    """
    monkeypatch.setenv("TENSORDATA_API_KEY", api_key)
    monkeypatch.setenv("TENSORDATA_STORAGE_ROOT", str(tmp_path / "artifacts"))
    from tensordata.config import get_settings

    get_settings.cache_clear()
    return TestClient(app)


def upload_csv(client: TestClient, headers: dict, content: bytes, asset_type: str = "timeseries"):
    asset = client.post("/api/v1/assets", headers=headers, json={
        "name": f"quality-reliability-{uuid4()}",
        "asset_type": asset_type,
        "owner": "quality-tests",
    }).json()
    upload = client.post(
        f"/api/v1/assets/{asset['id']}/artifacts",
        headers=headers,
        files={"file": ("sample.csv", content, "text/csv")},
    )
    assert upload.status_code == 201
    return upload.json()


def run_check(client: TestClient, headers: dict, artifact: dict, profile: str):
    response = client.post(
        f"/api/v1/artifacts/{artifact['id']}/quality-checks",
        headers=headers,
        json={"profile": profile, "executed_by": "quality-test-agent"},
    )
    assert response.status_code == 201
    return response.json()


def finding_ids(report: dict) -> list[str]:
    return [item["rule_id"] for item in report["findings_json"]]


def payload_path_for(artifact: dict):
    from tensordata.config import get_settings

    return get_settings().storage_root / artifact["sha256"][:2] / artifact["sha256"]


def test_empty_upload_fails_non_empty_rule(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        headers = {"X-API-Key": "quality-reliability"}
        artifact = upload_csv(client, headers, b"")
        report = run_check(client, headers, artifact, "tabular")
        assert report["status"] == "failed"
        assert finding_ids(report) == [
            "file.non_empty",
            "tabular.header_present",
            "tabular.rows_present",
        ]
        assert report["summary_json"]["measured_size_bytes"] == 0
        assert report["summary_json"]["sha256_verified"] is True


def test_on_disk_tamper_report_names_measured_bytes(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        headers = {"X-API-Key": "quality-reliability"}
        original = b"time,speed\n0,2.1\n1,2.4\n"
        artifact = upload_csv(client, headers, original)

        tampered = b"time,speed\n0,9.9\n1,2.4\n"  # same length, different bytes
        assert len(tampered) == len(original)
        payload_path_for(artifact).write_bytes(tampered)

        report = run_check(client, headers, artifact, "general")
        assert report["status"] == "failed"
        assert finding_ids(report) == ["file.sha256_matches_metadata"]
        # the report must name the bytes it actually examined, not the metadata
        assert report["summary_json"]["measured_sha256"] == sha256(tampered).hexdigest()
        assert report["summary_json"]["measured_sha256"] != artifact["sha256"]
        assert report["summary_json"]["sha256_verified"] is False


def test_general_report_cannot_substitute_tabular_gate(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        headers = {"X-API-Key": "quality-reliability"}
        artifact = upload_csv(client, headers, b"a,b\n1,2\n")

        # a passing general report exists…
        general = run_check(client, headers, artifact, "general")
        assert general["status"] == "passed"

        dataset = client.post("/api/v1/datasets", headers=headers, json={
            "name": f"gate-{uuid4()}",
            "owner": "quality-tests",
        }).json()
        version_payload = {
            "version": "1.0.0",
            "members": [{"artifact_id": artifact["id"], "role": "observations"}],
            "split_definition": {},
            "schema_refs": [],
            "transform_refs": [],
            "created_by": "test-agent",
        }
        # …but the csv artifact requires a tabular report: 422
        blocked = client.post(
            f"/api/v1/datasets/{dataset['id']}/versions",
            headers=headers, json=version_payload,
        )
        assert blocked.status_code == 422
        assert "tabular" in blocked.json()["detail"]

        # break the payload on disk so a subsequent tabular check genuinely fails
        payload_path_for(artifact).write_bytes(b"a,b\n1\n")  # malformed row
        failed_tabular = run_check(client, headers, artifact, "tabular")
        assert failed_tabular["status"] == "failed"
        assert "tabular.row_width" in finding_ids(failed_tabular)

        still_blocked = client.post(
            f"/api/v1/datasets/{dataset['id']}/versions",
            headers=headers, json=version_payload,
        )
        assert still_blocked.status_code == 422


def test_unknown_profile_rejected_by_schema(monkeypatch, tmp_path):
    with make_client(monkeypatch, tmp_path) as client:
        headers = {"X-API-Key": "quality-reliability"}
        artifact = upload_csv(client, headers, b"a,b\n1,2\n")
        response = client.post(
            f"/api/v1/artifacts/{artifact['id']}/quality-checks",
            headers=headers,
            json={"profile": "mesh", "executed_by": "quality-test-agent"},
        )
        assert response.status_code == 422  # Literal profile set, not a 500


def test_rule_crash_is_isolated_and_never_passes(monkeypatch, tmp_path):
    """A genuinely broken rule must surface as rule.execution_failed, not a pass."""
    payload = tmp_path / "crash.csv"
    payload.write_bytes(b"a,b\n1,2\n")
    rules = QUALITY_ENGINE.registry.get("general").rules
    victim = next(rule for rule in rules if rule.rule_id == "file.non_empty")

    def explode(ctx):
        raise RuntimeError("injected fault")

    monkeypatch.setattr(victim, "run", explode)
    result = QUALITY_ENGINE.run(
        "general", payload,
        expected_sha256=sha256(b"a,b\n1,2\n").hexdigest(),
        expected_size_bytes=8,
    )
    assert result.status == "failed"
    assert [f.rule_id for f in result.findings] == ["rule.execution_failed"]
    assert "file.non_empty" in result.findings[0].message
    assert result.summary["executed_rules"][0]["rule_id"] == "file.non_empty"
    # the other rules still ran and their evidence is intact
    assert result.summary["sha256_verified"] is True


def test_large_csv_streams_within_memory_bound(tmp_path):
    """Peak Python memory during a tabular check stays below the payload size."""
    row_count = 100_000
    duplicate_rows = 500
    path = tmp_path / "large.csv"
    base_row = ",".join(f"column-{i}-value" for i in range(9))  # + index = 10 fields
    with path.open("w", encoding="utf-8", newline="") as out:
        out.write(",".join(f"col_{i}" for i in range(10)) + "\n")
        for i in range(row_count - duplicate_rows):
            out.write(f"{i},{base_row}\n")
        for _ in range(duplicate_rows):
            out.write(f"0,{base_row}\n")

    from tensordata.quality import QualityEngine, build_default_registry

    engine = QualityEngine(build_default_registry())
    expected = sha256(path.read_bytes()).hexdigest()

    tracemalloc.start()
    result = engine.run(
        "tabular", path,
        expected_sha256=expected,
        expected_size_bytes=path.stat().st_size,
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    size = path.stat().st_size
    assert size > 10 * 1024 * 1024  # fixture really is a large payload
    assert peak < size, f"peak {peak / 1e6:.1f} MB must stay below payload {size / 1e6:.1f} MB"
    assert result.status == "passed"
    assert result.summary["row_count"] == row_count
    assert result.summary["duplicate_rows"] == duplicate_rows
    assert result.summary["missing_cells"] == 0
    assert result.summary["malformed_rows"] == 0
    assert result.summary["executed_rules"]  # provenance present on every report
