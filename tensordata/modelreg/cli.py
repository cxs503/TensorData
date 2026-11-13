"""CLI for the model asset registry.

Commands (all take ``--root`` / ``TENSORDATA_MODEL_REGISTRY_ROOT``)::

    python -m tensordata.modelreg.cli list
    python -m tensordata.modelreg.cli show MODEL[@VERSION]
    python -m tensordata.modelreg.cli verify MODEL[@VERSION]      # exit 1 on failure
    python -m tensordata.modelreg.cli register --manifest m.json --artifact path/to/weights.pt
    python -m tensordata.modelreg.cli predict MODEL[@VERSION] --input x.json --out y.json
    python -m tensordata.modelreg.cli inventory --scan /root/tensor-ecosystem

``predict`` accepts a JSON array of rows, ``{"inputs": [...]}``, a CSV (header
optional, column order = manifest input order) or ``-`` for stdin, and prints
per-target predictions plus any applicability-domain violations.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .loaders import load_model
from .registry import ModelRegistry, RegistryError
from . import schema


def _split_ref(ref: str) -> tuple[str, str | None]:
    if "@" in ref:
        model_id, version = ref.split("@", 1)
        return model_id, version
    return ref, None


def _emit(obj: Any, as_json: bool = True) -> None:
    if as_json or isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False, default=str))
    else:  # pragma: no cover - convenience
        print(obj)


def _read_inputs(path: str) -> list[list[float]]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text()
    text = raw.strip()
    if not text:
        raise SystemExit("predict: empty input")
    if text[0] in "[{":
        payload = json.loads(text)
        rows = payload.get("inputs") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise SystemExit("predict: JSON must be a list of rows or {'inputs': [...]}")
        if rows and not isinstance(rows[0], list):
            rows = [rows]
        return rows
    rows = [[float(v) for v in row] for row in csv.reader(io.StringIO(text)) if row]
    return rows


def cmd_register(args: argparse.Namespace) -> int:
    reg = ModelRegistry(args.root)
    manifest = json.loads(Path(args.manifest).read_text())
    artifacts = {rel: Path(src) for rel, src in (args.artifact or [])}
    for art in manifest.get("artifacts", []):
        rel = art["path"]
        if rel in artifacts:
            continue
        candidate = Path(args.artifact_dir or ".") / rel
        if candidate.is_file():
            artifacts[rel] = candidate
    body = reg.register(manifest, artifacts)
    print(json.dumps({
        "registered": f"{body['model_id']}@{body['version']}",
        "manifest_sha256": body["manifest_sha256"],
        "weights_sha256": next(a["sha256"] for a in body["artifacts"] if a["role"] == "weights"),
        "data_fingerprint": body["training_data"]["fingerprint"],
        "path": str(reg.model_dir(body["model_id"], body["version"])),
    }, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    reg = ModelRegistry(args.root)
    rows = reg.list_models()
    if args.json:
        _emit(rows)
    else:
        for row in rows:
            print(f"{row['model_id']}@{row['version']}\t{row.get('task_type')}\t"
                  f"{row.get('loader')}\tweights {str(row.get('weights_sha256'))[:12]}\t"
                  f"data {str(row.get('data_fingerprint'))[7:19]}\t{row.get('eval_status')}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    model_id, version = _split_ref(args.model)
    reg = ModelRegistry(args.root)
    _emit(reg.load_manifest(model_id, version))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    model_id, version = _split_ref(args.model)
    reg = ModelRegistry(args.root)
    report = reg.verify(model_id, version)
    _emit(report)
    return 0 if report["ok"] else 1


def cmd_predict(args: argparse.Namespace) -> int:
    model_id, version = _split_ref(args.model)
    reg = ModelRegistry(args.root)
    predictor = load_model(reg, model_id, version)
    rows = _read_inputs(args.input)
    report = predictor.predict_report(rows)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"wrote {args.out}: {len(report['outputs'])} row(s), "
              f"{len(report['columns'])} column(s), out_of_domain={report['out_of_domain']['n_out_of_domain']}")
    else:
        _emit(report)
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    from scripts.model_asset_inventory import build_inventory  # local script, optional

    inventory = build_inventory(scan_roots=args.scan, registry_roots=[args.root] if args.root else None)
    if args.out:
        Path(args.out).write_text(json.dumps(inventory, indent=2))
        print(json.dumps(inventory["summary"], indent=2))
    else:
        _emit(inventory)
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    """Fingerprint an ``.npz`` table exactly as a manifest would declare it."""
    import numpy as np

    with np.load(args.table) as data:
        arrays = {name: data[name] for name in (args.array or data.files)}
    extra = json.loads(args.extra) if args.extra else {}
    print(json.dumps({"fingerprint": schema.fingerprint_arrays(arrays, extra)["fingerprint"],
                      "arrays": schema.fingerprint_arrays(arrays, extra)["arrays"]}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tensordata-modelreg", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=None, help="registry root (default: env/config)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("register", help="publish a model version")
    p.add_argument("--manifest", required=True)
    p.add_argument("--artifact", nargs=2, action="append", metavar=("REL_PATH", "FILE"),
                   help="payload source for a manifest-declared artifact path (repeatable)")
    p.add_argument("--artifact-dir", default=None,
                   help="resolve manifest artifact paths relative to this directory")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("list", help="list registered models")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="print the manifest of MODEL[@VERSION]")
    p.add_argument("model")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify", help="recompute hashes and the data fingerprint")
    p.add_argument("model")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("predict", help="load the model and run a forward pass")
    p.add_argument("model")
    p.add_argument("--input", required=True, help="JSON rows, CSV path or '-' for stdin")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("inventory", help="scan for model weight files on disk")
    p.add_argument("--scan", nargs="*", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("fingerprint", help="fingerprint an .npz training table")
    p.add_argument("--table", required=True)
    p.add_argument("--array", action="append")
    p.add_argument("--extra", default=None, help="JSON object with split/identity binding")
    p.set_defaults(func=cmd_fingerprint)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RegistryError, schema.ManifestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())