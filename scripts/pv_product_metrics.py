#!/usr/bin/env python3
"""Collect the measured product metrics for the Physics Dataset Validator.

Two independent sources, no hand-copied numbers:

* **wall clock** — ``scripts/pv_demo.py`` is executed ``--runs`` times as a
  separate process (fresh interpreter each time, as a user would run it) and
  the process wall time is measured with ``time.monotonic``;
* **cost** — read from the platform ledgers: ``metered_usage`` (agent tokens,
  tool calls, wall seconds) and ``compute_ledger`` (cpu/wall seconds) for the
  missions that built, reviewed and productised the validator.

Usage::

    python3 scripts/pv_product_metrics.py --out docs/m22924/product_metrics.json

The ledger section is skipped (and reported as ``not_measured``) when the
database is not reachable from the caller, so the script is safe to run
anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO = REPO_ROOT / "scripts" / "pv_demo.py"

#: missions in the PROD-PV line: build (22061), independent reviews (22508-22510),
#: productisation (this mission).
LINE_MISSIONS = (22061, 22508, 22509, 22510, 22924)


def run_demo(input_dir: Path, runs: int, out_root: Path) -> dict[str, Any]:
    walls: list[float] = []
    cpu_seconds: list[float] = []
    digests: list[str] = []
    for index in range(runs):
        out_dir = out_root / f"run{index + 1}"
        command = [sys.executable, str(DEMO), "--input-dir", str(input_dir),
                   "--out-dir", str(out_dir), "--repeat", "1", "--quiet"]
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.monotonic()
        proc = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
        walls.append(time.monotonic() - started)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_seconds.append((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime))
        evidence = out_dir / "evidence.json"
        if evidence.exists():
            digests.append(json.loads(evidence.read_text(encoding="utf-8"))["result_digest"])
        if proc.returncode != 0:
            print(f"[warn] run {index + 1} exit={proc.returncode}: {proc.stderr[-400:]}",
                  file=sys.stderr)
    return {
        "command": " ".join([Path(sys.executable).name, "scripts/pv_demo.py",
                             "--input-dir", str(input_dir), "--repeat", "1"]),
        "runs": runs,
        "wall_seconds": walls,
        "wall_median": statistics.median(walls),
        "wall_min": min(walls),
        "wall_max": max(walls),
        "cpu_seconds": cpu_seconds,
        "cpu_median": statistics.median(cpu_seconds) if cpu_seconds else None,
        "cpu_source": "resource.getrusage(RUSAGE_CHILDREN) around the child process "
                      "(measured here, not from the platform ledger)",
        "unique_result_digests": sorted(set(digests)),
        "deterministic": len(set(digests)) == 1 and len(digests) == runs,
    }


def psql(sql: str) -> list[dict[str, Any]]:
    """Read-only query; returns [] when the platform database is unreachable."""
    db = os.environ.get("TP_PG_DB", "tensorplatform")
    command = ["psql", "-U", os.environ.get("TP_PG_USER", "foundation"), "-d", db,
               "--no-psqlrc", "-q", "-A", "-F", "\t", "-c", sql]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    lines = [line for line in proc.stdout.splitlines()
             if line.strip() and not line.strip().endswith(" rows)")
             and not line.strip().endswith(" row)")]
    if not lines:
        return []
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


def ledger_metrics(missions: tuple[int, ...]) -> dict[str, Any]:
    ids = ",".join(str(m) for m in missions)
    usage = psql(
        "select mission_id, coalesce(sum(tokens_used),0) as tokens, "
        "coalesce(sum(tool_calls),0) as tool_calls, "
        "coalesce(max(wall_seconds),0) as wall_seconds, count(*) as records "
        f"from metered_usage where mission_id in ({ids}) group by mission_id order by mission_id;")
    compute = psql(
        "select mission_id, coalesce(sum(cpu_seconds),0) as cpu_seconds, "
        "coalesce(sum(wall_seconds),0) as wall_seconds, count(*) as records "
        f"from compute_ledger where mission_id in ({ids}) group by mission_id order by mission_id;")
    if not usage and not compute:
        return {"status": "not_measured",
                "reason": "no metered_usage / compute_ledger rows exist for these missions "
                          "(the platform ledgers do not yet meter this product line); token and "
                          "compute cost are therefore reported from the local rusage measurement "
                          "in this file, never estimated",
                "missions": list(missions),
                "queries": ["metered_usage by mission_id", "compute_ledger by mission_id"]}
    total_tokens = sum(int(float(row["tokens"])) for row in usage)
    total_tool_calls = sum(int(float(row["tool_calls"])) for row in usage)
    total_agent_wall = sum(float(row["wall_seconds"]) for row in usage)
    total_cpu = sum(float(row["cpu_seconds"]) for row in compute)
    total_compute_wall = sum(float(row["wall_seconds"]) for row in compute)
    return {
        "status": "measured",
        "source": "tensorplatform.metered_usage + tensorplatform.compute_ledger "
                  "(read-only psql, no hand copy)",
        "missions": list(missions),
        "metered_usage": usage,
        "compute_ledger": compute,
        "totals": {
            "tokens": total_tokens,
            "tool_calls": total_tool_calls,
            "agent_wall_seconds": total_agent_wall,
            "agent_hours": total_agent_wall / 3600.0,
            "cpu_seconds": total_cpu,
            "compute_wall_seconds": total_compute_wall,
            "human_hours": 0.0,
            "human_hours_note": "no human operator is recorded in the platform ledgers for this "
                                "line; human review time is not metered, so it is reported as "
                                "not-measured rather than assumed",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PROD-PV product metrics")
    parser.add_argument("--fixture-dir", type=Path, default=REPO_ROOT / "examples" / "pv-demo")
    parser.add_argument("--real-input-dir", type=Path, default=None,
                        help="optional real dataset dir (measured in a separate section)")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--work-root", type=Path,
                        default=REPO_ROOT / "artifacts" / "pv-product-metrics")
    args = parser.parse_args(argv)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    work_root = args.work_root / stamp
    work_root.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "host_python": sys.version.split()[0],
        "fixture": run_demo(args.fixture_dir, args.runs, work_root / "fixture"),
        "cost": ledger_metrics(LINE_MISSIONS),
    }
    if args.real_input_dir:
        payload["real"] = run_demo(args.real_input_dir, args.runs, work_root / "real")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "cost"}, indent=2)[:1200])
    print("cost status:", payload["cost"]["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())