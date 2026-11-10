#!/usr/bin/env python3
"""Validate TensorData asset-rights manifests using the Python standard library."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "rights" / "manifests"
REQUIRED_TOP = {"manifest_version", "asset_id", "asset_type", "source", "rights", "provenance", "review"}
RIGHTS_STATES = {"unknown", "needs_review", "restricted", "approved", "prohibited"}
PURPOSE_FIELDS = {"permitted_purposes", "prohibited_purposes"}


def fail(path: Path, message: str) -> None:
    print(f"ERROR {path.relative_to(ROOT)}: {message}")


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return ["manifest root must be a JSON object"]
    missing = REQUIRED_TOP - data.keys()
    if missing:
        errors.append(f"missing top-level fields: {', '.join(sorted(missing))}")
        return errors
    if data["manifest_version"] != "tensordata.asset-rights.v1":
        errors.append("unsupported manifest_version")
    if not isinstance(data["asset_id"], str) or not data["asset_id"].strip():
        errors.append("asset_id must be a non-empty string")
    source = data["source"]
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        for key in ("source_type", "title", "uri", "acquired_at", "acquisition_method", "acquired_by"):
            if not str(source.get(key, "")).strip():
                errors.append(f"source.{key} is required")
    rights = data["rights"]
    if not isinstance(rights, dict):
        errors.append("rights must be an object")
    else:
        state = rights.get("status")
        if state not in RIGHTS_STATES:
            errors.append(f"rights.status must be one of {sorted(RIGHTS_STATES)}")
        for key in ("license_expression", "rights_holder", "redistribution", "commercial_use", "model_training"):
            if key not in rights or not str(rights[key]).strip():
                errors.append(f"rights.{key} is required")
        for key in PURPOSE_FIELDS:
            if not isinstance(rights.get(key), list):
                errors.append(f"rights.{key} must be an array")
        if state == "approved":
            if rights.get("license_expression") in (None, "", "NOASSERTION"):
                errors.append("approved rights require an established license_expression")
            if not str(rights.get("evidence_uri", "")).strip():
                errors.append("approved rights require evidence_uri")
            if not str(rights.get("rights_holder", "")).strip() or rights.get("rights_holder") == "unknown":
                errors.append("approved rights require an identified rights_holder")
            if not rights.get("permitted_purposes"):
                errors.append("approved rights require at least one permitted_purpose")
    review = data["review"]
    if not isinstance(review, dict):
        errors.append("review must be an object")
    elif isinstance(rights, dict) and rights.get("status") == "approved":
        for key in ("reviewed_by", "reviewed_at"):
            if not str(review.get(key, "")).strip():
                errors.append(f"approved manifest requires review.{key}")
        if review.get("status") != "approved":
            errors.append("rights.status=approved requires review.status=approved")
        if not review.get("decision_scope"):
            errors.append("approved manifest requires review.decision_scope")
    return errors


def main() -> int:
    if not MANIFEST_DIR.exists():
        print(f"ERROR missing manifest directory: {MANIFEST_DIR}")
        return 1
    manifests = sorted(MANIFEST_DIR.glob("*.json"))
    if not manifests:
        print("ERROR no rights manifests found; add a manifest or an explicit empty-state record")
        return 1
    failed = False
    for path in manifests:
        errors = validate(path)
        if errors:
            failed = True
            for error in errors:
                fail(path, error)
        else:
            print(f"OK {path.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
