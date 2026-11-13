# Ship-geometry dataset onboarding (GAP-CAD-T2-SHIPD-5415)

Two external hull-geometry sources are registered here as TensorData datasets, each with a
schema, pinned provenance, and a reproducible quality gate. Raw payloads are **not** committed
(`data/` is gitignored, and TensorData policy forbids committing generated/restricted data);
fetch with `python scripts/fetch_sources.py`.

| dataset | cardinality | X | y | rights | gate evidence |
|---|---|---|---|---|---|
| `shipd-30k-hull-design-vectors` | 30,000 | 45 design parameters | reconstructible Cw (Modified Michell, 8 Fn × 4 drafts) | **review_required** (upstream has no LICENSE file) | `artifacts/GAP-CAD-T2-SHIPD-5415/shipd/qa_summary.json` |
| `dtmb5415-design-space-dr` | 9,001 | 27 normalized design variables | Cw, az, xi5 at Fr = 0.25/0.33/0.41 | **CC-BY-4.0** (attribution required) | `artifacts/GAP-CAD-T2-SHIPD-5415/dtmb5415/{geometry_gate,train_ready_manifest,surrogate_baseline}.json` |

See [shipd.md](shipd.md) and [dtmb5415.md](dtmb5415.md), and the pipeline figure
`artifacts/GAP-CAD-T2-SHIPD-5415/gap_cad_t2_shipd_5415.png`.
