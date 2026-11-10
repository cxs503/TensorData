# TensorData Roadmap

## M0 — Architecture and contracts
- [x] Establish project boundary and principles
- [x] Define canonical data asset concepts
- [x] Define governance and release gates
- [x] Define TensorPlatform migration policy
- [x] Complete an initial, explicitly provisional code scan of TensorPlatform data capabilities
- [ ] Complete repository-wide dependency, caller, migration and runtime audit

## M1 — Minimal real service
- [x] Python package and application entry point
- [x] Environment configuration and health endpoint
- [x] Relational metadata persistence baseline (SQLite/PostgreSQL URL support; schema migrations still missing)
- [x] Filesystem artifact backend with SHA-256 content addressing
- [x] Basic DataAsset registration and catalog read APIs
- [x] DataArtifact upload, listing and content retrieval
- [x] API-key gate for all asset APIs
- [ ] Alembic schema migrations
- [ ] Full DataAsset/DataArtifact lifecycle and update/delete policy
- [ ] Dataset and immutable DatasetVersion registry
- [ ] JSON Schema validation
- [ ] Unit and API integration tests passing in CI
- [x] Docker-based local development entry point

## M2 — Trust and governance
- [ ] Source and rights registry with evidence-backed approval
- [ ] Provenance and lineage
- [ ] Quality rule execution and immutable reports
- [ ] Quarantine/approval/publication transitions
- [ ] Audit events and purpose-aware access checks

## M3 — Processing and connectors
- [ ] Profiling, cleaning and transformation contracts
- [ ] Connector SDK and first authorized source connectors
- [ ] Dataset manifest and export/resolve APIs
- [ ] Idempotency, retries and operational observability

## M4 — Tensor ecosystem integration
- [ ] TensorPlatform API client and workflow contract
- [ ] TensorKnowledge asset registration contract
- [ ] Domain validator plugin contract
- [ ] Ship/physics AI pilot datasets and evaluation feedback

## M5 — Scale when justified
- [ ] S3-compatible storage
- [ ] Columnar/large-scale query engine
- [ ] Streaming ingestion
- [ ] Search/vector index as derived indexes
- [ ] Distributed processing and high-volume scheduling

Scale components are gated by measured workload, not adopted pre-emptively.

## Current milestone note

The service is an early development baseline. The CI workflow has been added and is being used to expose/fix integration defects; do not call M1 complete until the current test suite passes and schema migration/authentication hardening is addressed.
