# TensorData

**AI-native data production, governance, and delivery infrastructure.**

TensorData is the data-asset infrastructure for the Tensor ecosystem. It turns heterogeneous evidence and observations into governed, versioned, discoverable, and reusable data products for AI training, agents, scientific computing, and future world models.

## Position in the Tensor ecosystem

- **TensorPlatform** runs agents and workflows: identity, orchestration, execution, tools, and compute coordination.
- **TensorData** manages data assets: acquisition, storage references, schemas, quality, provenance, lineage, versions, dataset assembly, and data delivery.
- **TensorKnowledge** produces and evolves explicit knowledge: concepts, claims, evidence relationships, theories, uncertainty, and knowledge validation.
- **Domain projects** produce and consume domain-specific observations, simulations, algorithms, and evaluations.

These systems integrate through explicit APIs and stable identifiers. They must not share private implementation modules or rely on shared business tables.

## Core principles

1. **Use-case driven:** define downstream tasks and acceptance tests before scaling collection.
2. **Evidence first:** preserve source artifacts and acquisition context; never silently overwrite raw evidence.
3. **Multimodal by design:** support text, tables, images, audio, video, time series, spatial data, scientific fields, and agent traces.
4. **Provenance by default:** every derived artifact must trace to inputs, transformations, versions, and responsible actors.
5. **Quality is executable:** quality rules produce machine-readable results and block promotion when required.
6. **Rights-aware:** record license, consent, restrictions, retention, and permitted purposes before use.
7. **Reproducible datasets:** a dataset version resolves to immutable membership, schema, transformation versions, and checksums.
8. **No fake readiness:** demos, synthetic examples, and production-verified capabilities are clearly distinguished.
9. **Open interfaces:** prefer interoperable formats and APIs; avoid unnecessary infrastructure duplication.
10. **Agent-operated, human-governed:** agents may produce and review assets, while high-impact releases require independent checks and explicit policy.

## Initial scope

The first milestone is a small, real, independently runnable data-asset service—not a full lakehouse platform.

- Canonical data-asset and dataset-version contracts
- Provenance, lineage, quality, and access-policy metadata
- Catalog and dataset registry
- Validation and promotion lifecycle
- API contracts for TensorPlatform and domain projects
- Migration inventory for reusable TensorPlatform data components

## Architecture documents

- [Architecture overview](docs/architecture/overview.md)
- [Data asset model](docs/architecture/data-asset-model.md)
- [Governance and quality](docs/governance/data-governance.md)
- [TensorPlatform migration plan](docs/migration/tensorplatform-migration.md)
- [Roadmap](docs/roadmap.md)

## Status

**Architecture foundation — implementation not yet production-ready.** The repository is being initialized. Features must not be described as operational until code, tests, and runtime evidence exist.
