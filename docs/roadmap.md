# TensorData Roadmap

## M0 — Architecture and contracts
- [x] Establish project boundary and principles
- [x] Define canonical data asset concepts
- [x] Define governance and release gates
- [x] Define TensorPlatform migration policy
- [ ] Review architecture against actual TensorPlatform implementation and TensorData constraints

## M1 — Minimal real service
- [ ] Python package and application entry point
- [ ] Configuration and health/readiness endpoints
- [ ] Relational metadata persistence and migrations
- [ ] Filesystem artifact backend with checksum verification
- [ ] DataAsset and DataArtifact CRUD
- [ ] Dataset and immutable DatasetVersion registry
- [ ] JSON Schema validation
- [ ] Unit and API integration tests
- [ ] Docker-based local development

## M2 — Trust and governance
- [ ] Source and rights registration
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
