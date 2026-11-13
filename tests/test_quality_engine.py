"""Unit tests for the quality engine package (no FastAPI, no DB).

These exercise the engine directly against real files in tmp_path — no mocks
of the check execution itself.
"""

import subprocess
import sys

import pytest

from tensordata.quality import (
    RULESET_VERSION,
    Profile,
    QualityEngine,
    Rule,
    RuleContext,
    RuleOutcome,
    RuleRegistry,
    UnknownProfileError,
    build_default_registry,
)


def make_engine() -> QualityEngine:
    return QualityEngine(build_default_registry())


def write_csv(tmp_path, content: bytes):
    path = tmp_path / "payload.csv"
    path.write_bytes(content)
    return path


def file_meta(path):
    from hashlib import sha256

    data = path.read_bytes()
    return {"expected_sha256": sha256(data).hexdigest(), "expected_size_bytes": len(data)}


class ExplodingRule(Rule):
    rule_id = "test.exploding"
    version = "9.9.9"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        raise RuntimeError("boom")


def rule_ids(result):
    return [finding.rule_id for finding in result.findings]


# ── registry ──────────────────────────────────────────────────────────────


def test_registry_lists_builtin_profiles_and_rejects_unknown():
    engine = make_engine()
    assert engine.registry.profile_names() == ["general", "hull-mesh", "tabular"]
    with pytest.raises(UnknownProfileError):
        engine.run("mesh", __import__("pathlib").Path("."), expected_sha256="", expected_size_bytes=0)


def test_registry_rejects_duplicate_profile_and_duplicate_rule():
    registry = RuleRegistry()
    profile = build_default_registry().get("general")
    registry.register(profile)
    with pytest.raises(ValueError):
        registry.register(profile)
    duplicated = Profile(
        name="broken",
        version="0.1.0",
        rules=(profile.rules[0], profile.rules[0]),
    )
    with pytest.raises(ValueError):
        registry.register(duplicated)


# ── general profile ───────────────────────────────────────────────────────


def test_general_passes_on_intact_payload(tmp_path):
    path = write_csv(tmp_path, b"time,speed\n0,2.1\n")
    result = make_engine().run("general", path, **file_meta(path))
    assert result.status == "passed"
    assert result.findings == []
    assert result.summary["size_bytes"] == path.stat().st_size
    assert result.summary["sha256_verified"] is True
    assert result.summary["measured_sha256"] == file_meta(path)["expected_sha256"]
    assert result.summary["measured_size_bytes"] == path.stat().st_size


def test_general_fails_on_empty_file(tmp_path):
    path = write_csv(tmp_path, b"")
    result = make_engine().run("general", path, **file_meta(path))
    assert result.status == "failed"
    assert rule_ids(result) == ["file.non_empty"]


def test_general_detects_tampered_payload(tmp_path):
    path = write_csv(tmp_path, b"time,speed\n0,2.1\n")
    meta = file_meta(path)  # metadata recorded before tampering
    path.write_bytes(b"time,speed\n0,9.9\n")  # same length: only the hash changes
    result = make_engine().run("general", path, **meta)
    assert result.status == "failed"
    assert rule_ids(result) == ["file.sha256_matches_metadata"]
    # the report must name the bytes it actually examined
    assert result.summary["measured_sha256"] == file_meta(path)["expected_sha256"]
    assert result.summary["sha256_verified"] is False


# ── tabular profile ───────────────────────────────────────────────────────


def test_tabular_counts_missing_duplicate_and_malformed_rows(tmp_path):
    path = write_csv(tmp_path, b"a,b\n1,2\n3,\n3,\n4,5,6\n")
    result = make_engine().run("tabular", path, **file_meta(path))
    assert result.status == "failed"  # row_width is an error
    assert result.summary["row_count"] == 4
    assert result.summary["column_count"] == 2
    assert result.summary["columns"] == ["a", "b"]
    assert result.summary["missing_cells"] == 2
    assert result.summary["duplicate_rows"] == 1
    assert result.summary["malformed_rows"] == 1
    finding_by_id = {f.rule_id: f for f in result.findings}
    assert finding_by_id["tabular.row_width"].severity == "error"
    assert finding_by_id["tabular.row_width"].count == 1
    assert finding_by_id["tabular.missing_cells"].severity == "warning"
    assert finding_by_id["tabular.missing_cells"].count == 2
    assert finding_by_id["tabular.duplicate_rows"].severity == "warning"
    assert finding_by_id["tabular.duplicate_rows"].count == 1


def test_tabular_duplicate_detection_strips_whitespace(tmp_path):
    path = write_csv(tmp_path, b"a,b\n1, 2\n 1 ,2\n")
    result = make_engine().run("tabular", path, **file_meta(path))
    assert result.status == "passed"
    assert result.summary["duplicate_rows"] == 1


def test_tabular_header_only_csv_fails_rows_present(tmp_path):
    path = write_csv(tmp_path, b"a,b\n")
    result = make_engine().run("tabular", path, **file_meta(path))
    assert result.status == "failed"
    assert rule_ids(result) == ["tabular.rows_present"]
    assert result.summary["row_count"] == 0
    assert result.summary["columns"] == ["a", "b"]


def test_tabular_empty_file_reports_non_empty_header_and_rows(tmp_path):
    path = write_csv(tmp_path, b"")
    result = make_engine().run("tabular", path, **file_meta(path))
    assert result.status == "failed"
    assert rule_ids(result) == ["file.non_empty", "tabular.header_present", "tabular.rows_present"]


def test_tabular_binary_payload_reports_single_parse_error(tmp_path):
    path = write_csv(tmp_path, b"\xff\xfe\xfaa,b\n1,2\n")
    result = make_engine().run("tabular", path, **file_meta(path))
    assert result.status == "failed"
    assert rule_ids(result) == ["tabular.csv_parseable"]
    # legacy behaviour: no csv statistics when parsing failed
    assert "row_count" not in result.summary


# ── versioning and rule isolation ─────────────────────────────────────────


def test_report_records_executed_rules_and_ruleset_version(tmp_path):
    path = write_csv(tmp_path, b"a,b\n1,2\n")
    result = make_engine().run("tabular", path, **file_meta(path))
    assert result.ruleset_version == RULESET_VERSION == "0.1.0"
    executed = result.summary["executed_rules"]
    assert executed[0] == {"rule_id": "file.non_empty", "version": "0.1.0"}
    assert all({"rule_id", "version"} == set(entry) for entry in executed)
    assert len(executed) == len(QualityEngine(build_default_registry()).registry.get("tabular").rules)


def test_crashing_rule_is_reported_as_error_never_passes(tmp_path):
    path = write_csv(tmp_path, b"a,b\n1,2\n")
    registry = RuleRegistry()
    registry.register(Profile(name="fragile", version="0.1.0", rules=(ExplodingRule(),)))
    result = QualityEngine(registry).run("fragile", path, **file_meta(path))
    assert result.status == "failed"
    assert rule_ids(result) == ["rule.execution_failed"]
    assert "test.exploding" in result.findings[0].message
    assert "RuntimeError" in result.findings[0].message
    assert "did not complete" in result.findings[0].message
    assert result.summary["executed_rules"] == [{"rule_id": "test.exploding", "version": "9.9.9"}]


def test_engine_package_does_not_import_fastapi():
    code = (
        "import sys; import tensordata.quality; "
        "assert 'fastapi' not in sys.modules, 'quality engine must stay framework-free'; "
        "print('ok')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "ok"
