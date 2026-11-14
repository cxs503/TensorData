# Physics Dataset Validator — CSV Adapter

**Status:** executable first slice, not a universal physics validator.

## Supported input

The first adapter accepts a CSV table with one row per observation/sample and a versioned JSON validation profile. It is suitable for exported field samples and small labelled fixtures. It does not yet read native NetCDF, HDF5, VTK, CGNS or solver-specific binary formats.

## Run

```python
from tensordata.quality import validate_physics_csv

report = validate_physics_csv(
    "ship_flow_fields.csv",
    "ship_flow_profile.json",
    rights_status="cleared",
)
print(report["overall_status"])
```

The report follows the TensorBench validation-report structure and records dataset/profile SHA-256 fingerprints. Register the report with the TensorData quality workflow after the integration adapter is implemented.

## Implemented checks

- Required variable presence.
- Numeric finite-value checks.
- Strictly increasing time/axis values after collapsing adjacent repeated samples.
- Explicit unit declaration checks (metadata-level only; no automatic unit conversion).
- Declared per-variable valid ranges.
- Entity-level split leakage when entity and split columns are present.
- Rights gate for profiles requiring cleared rights.

## Fail-closed behavior

- Unknown/missing units are inconclusive.
- Unsupported required checks (boundary/initial conditions, conservation, multimodal alignment) are inconclusive, never passed.
- Missing required columns fail.
- A profile requiring cleared rights fails unless caller passes `rights_status="cleared"`.

## Known limitations

1. CSV parsing loads rows into memory; large datasets need a streaming implementation.
2. Time monotonicity assumes rows are ordered by time. It is not suitable for interleaved/unstructured samples without a grouping key.
3. Unit checks verify declared metadata only; they do not validate physical dimensions or convert units.
4. Conservation checks need a domain-specific control volume, discretization, flux definitions and tolerance; they are intentionally not guessed.
5. The profile's domain owner must approve physical ranges and assumptions before the profile is used as a training admission gate.

## Pilot gate

Before using on TensorLBM ship-flow data, provide a permission-cleared CSV export, approve its units and axis semantics, add known-good and deliberately corrupted fixtures, and compare results with an independent domain review.
