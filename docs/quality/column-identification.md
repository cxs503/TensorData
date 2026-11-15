# Column field/unit identification (`tensordata.quality.fields`)

**Status:** implemented (PV stage-3 gap-filler), exercised end-to-end on real data by
`scripts/pv_pilot_ex1_kcs.py` (see `docs/pilots/PV-EX1-KCS-STAGE3-PILOT.md`).

## Why this exists

The physics CSV adapter (`docs/validators/PHYSICS_CSV_ADAPTER.md`) validates a table against a
**hand-declared** profile: it can say "the column called `Rt_kN` is a force declared in kN and
must convert to N", but it cannot answer the question every reviewer of a real export asks
first — *for each numeric column, what physical field is this and in which unit, and what
exact factor turns it into SI?* Without that, an acceptance run either trusts the column names
or falls back to `inconclusive` on everything.

`tensordata.quality.fields` answers it from evidence only and stays deterministic.

## Rules (all deterministic, no free-text guessing)

| Step | Evidence recorded in `basis` |
|---|---|
| exact symbol lookup (`Fn`, `one_plus_k`, `Rt`, `iE`, `S`) | `symbol_table` |
| case-insensitive fallback for unambiguous multi-character symbols | `symbol_table_lowercase` |
| unit suffix, **case sensitive** (`_kN` force vs `_kn` knot, `_kW`, `_deg`, `_ms` = m/s) | `unit_suffix:<suffix>` |
| suffix unit dimension equals the symbol dimension | `dimension_conflict:...` (→ `status="unit_conflict"`) |
| magnitude inside the declared physical range, evaluated in canonical SI | `magnitude_within_declared_range` / `..._outside_...` |
| the same field exported in two units must agree after conversion (`<= 1e-6` relative) | `cross_column_agreement:<other column>` |
| no suffix ⇒ the field's canonical unit is *assumed* (never silently high confidence) | `canonical_unit_assumed` |

Unknown columns are reported as `status="unknown"` with `source_unit=None`. The caller decides:
the pilot gate is `unknown_rate <= 10%` (`UNKNOWN_RATE_LIMIT`) and every unknown column must be
listed.

## Output contract

`profile_columns(headers, rows)` / `profile_columns_from_file(path)` return one entry per
numeric column with `field`, `quantity`, `dimension`, `role`, `source_unit`, `canonical_unit`,
`si_scale` (multiplicative factor: `value_source * si_scale = value_SI`), `si_offset`,
`declared_range`, `observed_canonical_range`, `confidence`, `basis`; plus the table-level
`numeric_columns / identified_columns / unknown_columns / unknown_rate / meets_unknown_limit /
redundancy_checks`.

`build_profile(report, ...)` turns the report into the **existing** physics validation profile,
so the same table is then re-checked by `validate_physics_csv` (required variables, finite
values, unit consistency, physical bounds, axis monotonicity). Unknown and conflicting columns
are listed in `profile.notes` rather than dropped silently.

`monotonic_axis_within_groups(rows, axis, group)` covers grouped exports: a variant-major
envelope restarts the axis per variant, so the file-level `monotonic_axis` check is
inapplicable — the property the export actually promises is monotonicity *inside* each group.

## Known limitations (unchanged from the adapter plus these)

1. The symbol table covers ship resistance / power / geometry columns. Other disciplines must
   add their own symbols **and** the physical ranges with a domain justification.
2. Single-letter ambiguous symbols (`S`, `B`, `T`) match only in exact case and are reported at
   `medium` confidence; they are not asserted as declared units.
3. A column with no unit suffix only gets the canonical unit as an assumption.
4. Magnitude ranges are sanity gates for ship-scale exports, not type-approval limits; a value
   outside the range lowers confidence and fails the bound check, and the range must be reviewed
   by the domain owner before it is used as an admission gate.
5. `unknown_rate <= 10%` is a *policy* threshold chosen for this pilot; on a table with few
   numeric columns a single unrecognised name already breaks it.