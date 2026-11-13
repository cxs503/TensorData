# Ship-D: 30,000 hull design vectors — access & integration

## What it is
`HullParameterization.Hull_Parameterization(45-vector)` generates a full parametric hull
(envelope, cross-section, bow, stern, bulb), and `gen_stl()` emits a closed triangulated hull
(transom + optional deck lid). `Calc_VolumeProperties()` gives an independent waterplane-integral
volume from a *different* discretisation — this is what makes a real consistency gate possible.

## Load
```python
import numpy as np
from tensordata.geometry import load_triangles, volume_below
import sys; sys.path.insert(0, "data/raw/shipd")      # after scripts/fetch_sources.py --dataset shipd
if not hasattr(np, "trapz"): np.trapz = np.trapezoid   # vendor code predates numpy 2
from HullParameterization import Hull_Parameterization as HP

X = np.load("data/raw/shipd/InputVectors_30k.npy")     # (30000, 45)
hull = HP(X[0]); hull.gen_stl(NUM_WL=40, PointsPerWL=200, bit_AddTransom=1,
                              bit_AddDeckLid=1, namepath="/tmp/hull_00000")
tris, stats = load_triangles("/tmp/hull_00000.stl")
print(stats.volume_abs, stats.is_closed, volume_below(tris, hull.WL)[:2])
```

## Quality gate (TensorData `hull-mesh` profile + physical cross-checks)
`python scripts/shipd_geometry_qa.py --n 100 --workers 16 --out artifacts/GAP-CAD-T2-SHIPD-5415/shipd`

Per hull: profile `hull-mesh` (parse, ≥1000 triangles, no degenerate faces, closed manifold,
finite volume, sanities, port/starboard symmetry) plus
mesh volume vs waterplane-integral volume (≤2%), submerged volume (≤3%), length vs LOA (≤5%),
beam vs `Calc_Max_Beam_PC()` (≤2%), depth vs `Dd` (≤2%), Cb in (0.2, 0.9), parameter constraints,
and duplicate detection (parameter-vector and shape-fingerprint).

**Measured result (100 sampled configs, seed 20261113): 53 pass / 47 fail; volume agreement
max 0.55% (mean 0.086%), submerged volume max 13.6%.** Failures are dominated by beam vs the
vendor's max-beam path and by 3 hulls where the vendor builder itself raises — see the report.
The published `sample_Hull_Mesh.stl` needs winding repair (226,238 faces re-oriented) before its
volume is meaningful (10.397 vs 10.295 m³ integral ⇒ 0.99%); `load_triangles()` does this.

## Rights
Upstream `noahbagz/ShipD` carries **no license file** → `rights_status=review_required`.
Evaluation/research only; do not redistribute the payload or use it commercially until reviewed.
