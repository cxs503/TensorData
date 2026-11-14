# Physics Dataset Validator — TensorData Integration

**Status:** profile contract / initial integration design. This document does not claim a production physics validator exists.

## Ownership

TensorData owns dataset identity, immutable version manifests, quality report storage, provenance and rights/lifecycle state. The Physics Dataset Validator is a profile-driven validation capability. TensorBench owns the cross-product report contract. TensorPhysics and solver repositories own domain-specific physical acceptance rules and trusted reference cases.

Do not create another dataset registry, copy dataset bytes into a separate catalog, or treat a checksum as proof of scientific validity.

## Pipeline

1. Resolve a TensorData dataset ID and immutable version.
2. Verify manifest, artifact hashes, rights state and lineage.
3. Resolve a versioned validation profile (schema: `schemas/physics-validation-profile.schema.json`).
4. Inspect array metadata and run applicable deterministic checks.
5. Record per-check applicability, formula/method, variables, units, assumptions, tolerance and measured residual.
6. Emit TensorBench-compatible validation report and attach its reference to the TensorData quality workflow.
7. Permit downstream training only when the existing rights and dataset admission policies also pass.

## Check families

| Family | Minimum metadata | Example failure |
|---|---|---|
| Structural | dimensions, dtype, coordinate/time axes | NaN/Inf, malformed shape, non-monotone time |
| Dimensional | variable units and coordinate units | velocity labelled as pressure |
| Boundary/initial | declared condition type, location, value, tolerance | required boundary absent or violated |
| Conservation | control volume, density/flux/field, discretization | mass/energy residual exceeds tolerance |
| Physical bounds | declared material/flow regime and admissible range | negative density or impossible state |
| Multimodal alignment | timestamps, frame, CRS/mesh mapping | camera/sensor/simulation misalignment |
| Leakage | entity, trajectory, temporal window, split manifest | same trajectory crosses train/test |

A check is `not_applicable` if its assumptions are not met. Missing required metadata is `inconclusive` or a failure according to the profile; it must never silently pass.

## First ship-flow pilot

Use a permission-cleared TensorLBM/TensorPhysics ship-flow dataset. Start with structural, unit, coordinate/time and provenance checks. Add physical checks only after the domain owner specifies the governing variables, equations, discretization, control volume and tolerances.

Required negative fixtures: unit-scale mismatch, shuffled timestamps, missing boundary metadata, coordinate-frame mismatch, deliberately broken conservation, and train/test trajectory leakage. Label all synthetic corruptions.

## Exit gate

The first executable increment must demonstrate:
- dataset version and artifact hashes resolve correctly;
- known-good fixture passes applicable deterministic checks;
- each corrupted fixture is detected by its intended check;
- unknown units and missing required metadata do not pass;
- report links to exact input versions and records formulas/assumptions;
- no rights-uncleared dataset is promoted to training.
