# pv-demo input fixture

`demo-resistance.csv` is a **synthetic** input for `scripts/pv_demo.py`. It is
generated arithmetic, not measurement: it exists so the demo runs for a third
party with no private data in reach.

- 6 rows, Froude grid `Fn = 0.15 … 0.30`
- 8 numeric columns: `Fn, V_kn, Rt_kN, Pe_kW, Ct, CF, S, iE_deg`
- consistency: `V = Fn·sqrt(g·Lpp)` with `Lpp = 230 m`, `Rt = ½·ρ·Ct·S·V²` with
  `ρ = 1025 kg/m³`, `S = 9424 m²`, `Pe = Rt·V`, `iE` a linear ramp in `Fn`.
  `Ct`, `CF` are illustrative smooth curves — **not** a validated resistance or
  friction model, and no physical claim is attached to them.
- the `V_kn` / `Rt_kN` pair is deliberately present: it exercises the
  `_kn` (knot) / `_kN` (kilonewton) case trap that the validator must resolve.

Do not cite this file as evidence of anything. Real acceptance evidence lives in
`docs/pilots/PV-EX1-KCS-STAGE3-PILOT.md` and `docs/m22924/`.