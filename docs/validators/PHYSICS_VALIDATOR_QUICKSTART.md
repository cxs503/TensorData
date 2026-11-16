# Physics Dataset Validator — quickstart (product 1.0.0)

Column-level acceptance for physics CSV field tables (ship resistance exports,
CFD sweep tables, model-test tables). You give it a CSV; it tells you, per
column, which physical field it is, which unit it carries, the exact SI
conversion factor, and whether the table is admissible — with a machine-readable
report whose every number traces back to the input bytes.

This is a *data* validator. It does **not** certify model accuracy; see
[Limitations](#limitations).

- Product: `physics-dataset-validator` 1.0.0 (report schema 0.1.0)
- Release history: [../CHANGELOG.md](../CHANGELOG.md)
- Contract: [PHYSICS_DATASET_VALIDATOR.md](PHYSICS_DATASET_VALIDATOR.md),
  [PHYSICS_CSV_ADAPTER.md](PHYSICS_CSV_ADAPTER.md)
- Column identification catalogue: [../quality/column-identification.md](../quality/column-identification.md)

## 1. Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .            # Python >= 3.11; no network services needed
```

The validator is a pure library path — no API server, no database, no GPU.

## 2. Run the demo (one command, no private data)

```bash
python3 scripts/pv_demo.py
```

Expected (verbatim shape, timings vary):

```
physics-dataset-validator 1.0.0 (report schema 0.1.0)
  demo-resistance.csv          verdict=passed       identified=8/8 unknown=0 baseline=failed
  injections detected: 4/5
  wall median 0.003s over 3 run(s); digest d8bc706997f308e1
  artifacts: artifacts/pv-demo/<utc-stamp>
```

`baseline=failed` is part of the demo: the same file is also validated through
the naive case-insensitive suffix lookup (the first thing anyone writes), which
collapses `V_kn` (knots) onto `kn` (kilonewton) and rejects a valid dataset.
`injections detected: 4/5` is measured, not decorative — see
[What the demo measures](#5-what-the-demo-measures).

Exit code `0` = every input passed, `1` = at least one did not, `2` = bad input
path. Artifacts (`evidence.json`, per-file `*.report.json`, generated profiles)
are written under `artifacts/pv-demo/<utc-stamp>/`, one subdirectory per repeat.

## 3. Validate your own CSV

```bash
python3 scripts/pv_demo.py --input-dir path/to/csvs --out-dir artifacts/pv-run --repeat 1
```

Input requirements: UTF-8 (BOM tolerated) CSV, one header row, at least one data
row. Column names are matched against the field table in
`tensordata/quality/fields.py`; a `_<unit>` suffix (`Rt_kN`, `V_kn`, `Pe_kW`,
`iE_deg`) is resolved **case-sensitively before** SI normalization. A
variant-major export (a categorical column that repeats, e.g. `variant`) gets
its axis monotonicity checked inside each group instead of across the file.

Library use (no CLI):

```python
from tensordata.quality import profile_columns_from_file, build_profile, validate_physics_csv

report = profile_columns_from_file("table_v1.csv")
profile = build_profile(report, profile_id="my-run", axis_columns=["Fn"])
# ... write profile to JSON, then:
verdict = validate_physics_csv("table_v1.csv", "my.profile.json")
print(verdict["product_version"], verdict["overall_status"])
```

Reproduce the acceptance run of the shipped pilot inputs (internal data, not in
this repository):

```bash
python3 scripts/pv_demo.py \
  --input-dir /root/ship-performance-platform-incoming/ship-performance-platform/docs/prereg/ex1_kcs \
  --out-dir artifacts/pv-demo/kcs-ex1 --repeat 1
```

## 4. Read the output

Per file, `evidence.json` → `datasets[i]`:

| field | meaning |
|---|---|
| `verdict` | `passed` / `failed` / `inconclusive` (inconclusive is never a pass) |
| `columns_report[]` | per column: `field`, `source_unit`, `canonical_unit`, `si_scale`, `confidence`, `basis` |
| `unknown_columns`, `unknown_rate` | columns with no field identification, and their ratio against the 10% gate |
| `review_required_columns` | columns whose unit is *assumed* from the canonical field (confidence `medium`) — a domain owner must confirm them |
| `checks[]` | every executed check with its state; unimplemented checks appear as `inconclusive` |
| `closures` | independent physics identities computed from the SI-converted columns (implied density, `Pe = Rt·V`, `V_kn` vs `V_ms`) |
| `baseline` | the same file through the naive suffix lookup, for comparison |
| `sha256` | fingerprint of the exact input bytes |

`report.overall_status` semantics: any required check `failed` ⇒ `failed`; no
failure but an `inconclusive`/`not_measured` required check ⇒ `inconclusive`;
otherwise `passed`. The report stamps `product_id`, `product_version` and the
input fingerprints, so a verdict is bound to the version that produced it.

## 5. What the demo measures

| measurement | how it is produced |
|---|---|
| identification coverage | identified numeric columns / numeric columns |
| review load | columns with `confidence != high` (assumed canonical units) |
| quality vs baseline | the file re-validated with case-insensitive suffix units |
| injected defects | 5 injections (out-of-range ×100, ×10 scale error, unit mislabel in the profile, renamed column, non-finite cell) re-run through the same pipeline |
| wall clock | per-run timing inside the process plus `scripts/pv_product_metrics.py` process-level timing |
| reproducibility | `result_digest` = SHA-256 over the canonicalised verdict payload; identical across runs |
| cost | `scripts/pv_product_metrics.py` reports measured wall/CPU seconds and queries the platform cost ledgers |

## 6. Limitations (measured, do not over-read the verdict)

1. **`physical_bounds` is a magnitude window, not an identity.** Scaling
   `Rt_kN` ×10 stays inside the declared range `(0, 5e7) N` and passes (measured:
   the ×10 injection is *not* reported by the range check). The
   implied-density closure does catch it. Use both.
2. **The unknown-rate gate is a ratio.** One renamed column in a 17-column table
   is 5.9% < 10%, so the verdict stays `passed`; the column is listed under
   `unknown_columns` and is excluded from range checks. Treat a non-empty
   `unknown_columns` list as "do not consume these columns yet".
3. **Assumed units are assumptions.** Dimensionless or single-letter columns
   (`Fn`, `Ct`, `S`) get `confidence: medium` with basis
   `canonical_unit_assumed`; the demo reports them as review load.
4. **Scope of fields.** Only the field table shipped in
   `tensordata/quality/fields.py` (ship resistance/flow domain). Other
   disciplines need their own `FIELDS` entries with justified ranges.
5. **Whole file in memory.** The adapter reads the CSV fully; large tables need
   streaming (not implemented).
6. **No EFD baseline.** A `passed` verdict means the data are structurally and
   physically admissible. Towing-tank comparison of *model* accuracy is a
   different acceptance gate and is not measured here.