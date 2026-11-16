# Changelog

All notable changes to TensorData are recorded here. Version numbers refer to the
deliverable that produces verdicts, not to the repository.

The **Physics Dataset Validator** (`physics-dataset-validator`) is the first
product line with its own version: its identity is stamped into every emitted
validation report (`product_id` / `product_version`) and defined in
`tensordata/quality/version.py`. Versioning rules are documented in that module:
a MAJOR bump means a verdict can flip on unchanged data.

## [1.0.0] - 2026-11-16 — Physics Dataset Validator

First supported release of the column-level acceptance validator for physics
CSV field tables. Content is the accumulated #7/#8/#9/#10/#11 chain; this
release adds no new check semantics — it adds the product surface (identity,
changelog, quickstart, one-command demo) and the packaging needed to consume
the validator as a product.

**Validator**
- `tensordata.quality.physics_csv.validate_physics_csv` — CSV field-table
  adapter (`dataset.finite_values`, `dataset.units_resolvable`,
  `dataset.physical_bounds`, `dataset.axis_monotonic.*`, `dataset.rights_cleared`,
  plus the declared-but-unimplemented checks reported as `inconclusive`, never
  as `passed`). Emits a TensorBench-compatible report with input fingerprints.
- `tensordata.quality.units` — explicit SI registry; unknown units stay
  `inconclusive`; case is significant before normalization so the force suffix
  `_kN` cannot be confused with the knot suffix `_kn`.
- `tensordata.quality.fields` — per-column field/unit identification with the
  exact SI conversion factor, confidence and `basis`; unknown-rate gate
  (limit 10%); grouped-axis check for variant-major exports
  (`monotonic_axis_within_groups`).
- `tensordata.quality` engine — streaming structure/tabular/integrity rules
  with rule-crash isolation.

**Product surface (new in 1.0.0)**
- Product identity: `physics-dataset-validator` 1.0.0, report schema 0.1.0
  (`tensordata/quality/version.py`, exported from `tensordata.quality`).
  `validate_physics_csv` now stamps the identity from that single source
  instead of hard-coded literals.
- `scripts/pv_demo.py` — one-command demo/CLI (`python3 scripts/pv_demo.py`):
  runs the shipped library on a
  CSV directory, prints one verdict per file, and measures identification
  coverage, review load, baseline comparison, injected-defect detection, wall
  clock and a deterministic `result_digest`.
- `examples/pv-demo/demo-resistance.csv` — bundled **synthetic** demo input so
  the demo runs with no private data.
- `docs/validators/PHYSICS_VALIDATOR_QUICKSTART.md` — third-party quickstart:
  install, demo, bring-your-own-CSV, output reference, limitations.
- `scripts/pv_product_metrics.py` — measured product metrics (process wall/CPU
  time across repeated runs, determinism, platform-ledger cost lookup).

**Known limitations in 1.0.0** (measured, see
`docs/m22924/PROD-PV-PRODUCTIZATION.md`)
- `physical_bounds` is a magnitude sanity window, not a cross-column identity:
  scaling `Rt_kN` by 10 keeps inside the declared range `(0, 5e7) N` and passes.
- The unknown-rate gate is a ratio: on a 17-column table a single renamed
  column (5.9%) passes the gate. The column is still listed in the profile
  `notes.unknown_columns` and is not range-checked.
- Columns whose unit can only be assumed from the canonical field (dimensionless
  quantities such as `Fn`, `Ct`, `S`) are reported with `confidence: medium`
  and need a domain owner's confirmation; they are counted as review load, not
  as automation.
- No EFD/towing-tank accuracy baseline: the validator accepts *data*, it does
  not certify *model* accuracy.

## [0.1.0] - 2026-11-10 — Governance core

Initial service: FastAPI app and API-key gate; asset/artifact registry with
content-addressed upload and SHA-256 metadata; dataset registry with immutable
`DatasetVersion` manifests and canonical-JSON digest; append-only provenance
activity records with validated artifact references; lineage traversal;
executable quality engine with immutable reports; model asset registry
(`model-manifest/1.0`) with digest verification; Alembic baseline migrations;
CI for tests/lint and rights-manifest validation.

**Not production-ready at 0.1.0** (unchanged in 1.0.0 of the validator):
evidence-backed rights approval, scoped identity/authorization, S3-compatible
storage, retention/garbage collection, deployment hardening.

[1.0.0]: docs/validators/PHYSICS_VALIDATOR_QUICKSTART.md
[0.1.0]: README.md#current-implementation