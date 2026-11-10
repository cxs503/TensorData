# Quality engine design

Stage-1 modularization of the artifact quality checks. The engine is a pure
library under `tensordata/quality/` — it imports no FastAPI, SQLAlchemy or
settings modules (enforced by test) — while `main.py` keeps only path
resolution, one engine call, and report persistence. Behavior is identical to
the pre-migration inline implementation; see
[audit-2026-11-10.md](audit-2026-11-10.md) for the baseline and the
differential evidence behind that claim.

## Module map

```
tensordata/quality/
├── base.py      Rule/Profile/Finding/EngineResult types + streaming scans
├── registry.py  RULESET_VERSION, RuleRegistry, build_default_registry()
├── engine.py    measure_file() + QualityEngine.run()
├── rules/
│   ├── integrity.py     file.non_empty / size_matches_metadata / sha256_matches_metadata
│   └── csv_structure.py tabular.* rules + CsvSummaryRule
└── profiles/
    ├── general.py       3 integrity rules
    └── tabular.py       integrity + 7 CSV rules (composition, legacy order)
```

## Lifecycle of one check

1. The API layer resolves the artifact to a local file path (404/501 handling
   stays in the endpoint).
2. `QualityEngine.run(profile, path, expected_sha256=…, expected_size_bytes=…)`
   measures the payload once in 1 MiB chunks (`size_bytes`, `sha256`).
3. Rules execute in profile order. `RuleContext.csv_scan()` memoizes a single
   streaming CSV pass shared by all tabular rules — the file is read twice per
   check at most (binary measure pass + CSV pass), never held whole.
4. A rule that raises is isolated: it contributes a `rule.execution_failed`
   error finding naming the rule, and the report fails. A broken rule can
   never masquerade as a pass, and one bad rule does not take down the check.
5. The engine returns an `EngineResult`; the endpoint persists it verbatim as
   a `QualityReport` row.

## Rule contract

```python
class MyRule(Rule):
    rule_id = "domain.thing_checked"   # stable, dotted, never renamed
    version = "1.0.0"                  # bump on any behavior change

    def run(self, ctx: RuleContext) -> RuleOutcome:
        return RuleOutcome(findings=[...], summary={...})
```

- Findings carry `severity` ∈ `error | warning | info`. The report status is
  `failed` iff any error-severity finding fired.
- Rule summaries merge into the report summary; keys must be prefixed to
  avoid collisions (`row_count`, `columns`, … are tabular-owned).
- Rules see only `ctx.path`, the recorded metadata, and shared scans — no DB,
  no request objects.

## Profiles and registry

A `Profile` is a named, versioned, ordered composition of rules. The tabular
profile composes the general rules first so finding order matches the legacy
implementation. `RuleRegistry` rejects duplicate profile names and duplicate
rule ids inside a profile; `build_default_registry()` is the single wiring
point for the built-in `general` and `tabular` profiles. Adding a scientific
profile (timeseries, field, mesh, multimodal) means adding a `Profile` and
registering it — no engine changes (interface drafts: stage 2, design only).

## Versioning contract

- `RULESET_VERSION` (`"0.1.0"`) is the externally pinned ruleset string stored
  on every report and snapshotted into dataset manifests. It changes only
  when rule behavior changes meaningfully.
- Each rule carries its own `version`. Every report records the exact rules
  that executed in `summary_json["executed_rules"]` as
  `{"rule_id", "version"}` pairs, so a historical report names the exact
  implementations that produced its verdict.
- The report also records `measured_sha256` / `measured_size_bytes` — the
  bytes it actually examined, not the metadata — so post-hoc tampering is
  distinguishable from a check that ran against different bytes.

## Summary schema

Base keys (legacy-compatible): `size_bytes` (measured), `sha256_verified`.
Tabular keys on successful parse: `row_count`, `column_count`, `columns`,
`missing_cells`, `duplicate_rows`, `malformed_rows`.
Additive provenance keys introduced by the engine (safe for existing
consumers; tests assert per-key, not set equality): `measured_sha256`,
`measured_size_bytes`, `profile_version`, `executed_rules`.

## Memory model

The binary pass streams 1 MiB chunks. The CSV pass streams via `csv.reader`
over an open handle; duplicate detection stores a 12-byte SHA-256 prefix per
distinct row (~fixed 96-bit digest, negligible collision odds at any
realistic row count) instead of the row text. Auxiliary memory is therefore
O(distinct rows × small constant), not O(payload bytes); the large-file test
holds peak Python allocations below the payload size for a 14 MB, 100 K-row
fixture (measured ratio ≈ 0.7; wider real-world rows improve it).

## Compatibility guarantees (stage 1)

- API paths, status codes and response shapes unchanged; `ruleset_version`
  still `"0.1.0"` (test-pinned).
- Rule ids, severities, messages and finding order byte-identical to the
  legacy implementation — verified by a differential harness that executes
  the git-extracted legacy block and the engine over a 36-case battery
  (empty, header-only, blank headers, malformed rows, whitespace duplicates,
  BOM, CRLF, quoted newlines, binary junk, mid-row `csv.Error`, tampered
  metadata).
- No schema migration needed: reports land in the existing `quality_reports`
  table (migration 0002 round-trip covered by tests).

## Audit findings addressed

| Audit item | Resolution |
|---|---|
| D1 report stored metadata hash, not measured | `measured_sha256`/`measured_size_bytes` recorded on every report |
| D2 rule exception → HTTP 500, no report | isolated as `rule.execution_failed` error finding; report still persisted |
| D3 no per-rule versions | per-rule `version` + `executed_rules` provenance |
| D4 duplicate set held full row text | fixed-size 12-byte digests |
| D5 migration test missed 0002 | upgrade/downgrade round-trip asserts `quality_reports` |

## Known limitations (carried, not fixed in stage 1)

- The dataset-version gate trusts the latest stored report plus metadata
  equality; it does not re-measure payload bytes at gate time. Detecting
  post-check on-disk tampering requires re-running the check (the tamper is
  always visible in the check's `measured_sha256`).
- Quality pass is an integrity/structure verdict only — it is explicitly not
  a copyright or authorization approval (rights stay governed by
  `rights_status` / `allowed_purposes`).
- Duplicate counting is exact-duplicate over whitespace-normalized rows;
  near-duplicates (e.g. float formatting differences) are not detected.
