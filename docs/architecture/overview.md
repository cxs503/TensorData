# TensorData Architecture Overview

## Mission
TensorData provides governed data-asset lifecycle infrastructure for the Tensor ecosystem. It makes data discoverable, traceable, quality-controlled, versioned, permissioned and usable by AI training, agents and scientific computing.

## Bounded contexts
- **TensorData owns:** data-source/acquisition records; raw and derived artifact references; catalog, schemas, datasets and immutable versions; transforms and validation results; provenance, lineage, rights, quality gates and data delivery.
- **TensorPlatform owns:** agent identity/runtime, scheduling, orchestration, tools, workflow execution, compute coordination and agent collaboration. It initiates jobs but calls TensorData contracts for data operations.
- **TensorKnowledge owns:** concepts, claims, theories, evidence interpretation, uncertainty and knowledge evolution. Its outputs are registered as assets in TensorData.
- **Domain projects own:** domain schemas, solvers, experiment protocols, scientific interpretation and domain evaluation.

Systems integrate through explicit APIs and stable identifiers. They must not share private modules or business database tables.

## Logical architecture
1. Connectors and ingestion: authorized source discovery and batch/stream intake.
2. Artifact layer: immutable payloads in pluggable object/filesystem storage; database stores metadata and references.
3. Catalog and registry: assets, datasets, schemas, tags, owners, states and versions.
4. Processing: validation, profiling, cleaning, transformation and packaging.
5. Trust plane: provenance, lineage, rights, access policy, audit and quality gates.
6. Delivery: dataset resolution, export, API and SDK.
7. Agent integration: TensorPlatform orchestrates work through public contracts; it is not a runtime dependency.

## Canonical lifecycle
DISCOVERED → REGISTERED → INGESTED → PROFILED → TRANSFORMED → VALIDATED → APPROVED → PUBLISHED → DEPRECATED.

Not every asset passes every state. Failed or restricted assets remain visible with explicit status. Published dataset versions are immutable; corrections create new versions.

## Asset classes
- Evidence: source documents, observations, sensor records, experiment files, simulation outputs, media and logs.
- Structured data: extracted entities, tables, measurements, time series, spatial and multimodal alignment records.
- Knowledge assets: claims, concepts, methods, relationships and evidence bundles.
- Training assets: samples, labels, trajectories, splits, preference pairs and evaluation sets.
- Capability assets: models, algorithms, programs and workflows. Execution lifecycle remains with the relevant platform.

These are asset classes, not a mandatory linear ETL pipeline. One evidence asset can produce many derived assets.

## Cross-cutting requirements
Every asset has a stable identifier, type, creation time, owner, lifecycle state and provenance status. Where applicable record source, rights, purpose restrictions, schema, checksum, storage location, quality, lineage and retention.

Separate payload from metadata. Large binary/scientific payloads belong in object or specialized storage; relational metadata belongs in a transactional catalog. Do not store large payloads in Git or relational rows.

## Initial deployment boundary
Start with one independently runnable service, relational metadata store and local filesystem artifact backend. Storage interfaces must allow later S3-compatible storage. Do not introduce Kafka, Spark, Iceberg, graph databases, vector databases or multiple orchestrators until measured requirements justify them.

## Non-goals
- Rebuilding TensorPlatform orchestration
- Owning general model training execution or GPU scheduling
- Replacing TensorKnowledge reasoning
- Building a universal lakehouse before real workloads exist
- Treating vector search as the canonical data model
- Declaring synthetic or unverified data to be ground truth
