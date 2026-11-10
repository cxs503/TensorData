# Canonical Data Asset Model

## Design goals
Cover files and structured records without assuming every asset is a table. Preserve immutable source evidence and enable reproducible dataset versions across multimodal and scientific data.

## Core entities

### DataAsset
A catalogued logical asset: asset_id (stable opaque ID), name, asset_type, description, lifecycle_state, owner, created_at, updated_at, provenance_status, sensitivity and tags.

### DataArtifact
A concrete immutable payload: artifact_id, asset_id, artifact_role (raw/intermediate/derived/export), storage_uri, media_type, size_bytes, checksum algorithm/value, created_at, producer, transform_id, optional schema_id, format and encoding.

### DataSource
A registered origin: source_id, source_type, name, locator, rights_status, license, terms_uri, allowed_purposes, accessed_at, acquisition_method and acquisition_actor. Never store credentials or secrets here.

### DataSchema
A versioned machine-readable structure: schema_id, schema_version, format, definition_uri and compatibility.

### Dataset
A logical collection: dataset_id, name, description, intended_uses, owner, status and current_version.

### DatasetVersion
An immutable snapshot: dataset_version_id, dataset_id, version, members (asset/artifact references and optional record selectors), schema_versions, transform_versions, split_definition, quality_report_refs, rights_summary, created_at and manifest_checksum. Any membership, schema, transform or split change creates a new version.

### Transform
A versioned processing specification: transform_id, version, name, implementation_ref, input_contract, output_contract, parameters, code_digest, environment_digest and created_by.

### QualityReport
An immutable validation result: report_id, subject_ref, rule_set_ref, status, metrics, findings, executed_at and executor.

### LineageEdge
A directed relationship: from_ref, to_ref, relationship, activity_ref and created_at.

### AccessPolicy
A machine-evaluable policy: subject, resource_ref, allowed_actions, allowed_purposes, conditions, validity window and decision_source.

### ProvenanceRecord
A W3C PROV-inspired record of input/output entities, activity, parameters, code/environment digest, responsible agent/person/service, timestamps and evidence references.

## Initial asset taxonomy
document, table, image, audio, video, timeseries, spatial, point_cloud, mesh, scientific_field, knowledge_bundle, agent_trace, training_sample, model_artifact, other.

Do not encode domain semantics into the global type list. Domain projects define schemas and profiles.

## Identity and versioning
Identifiers are opaque and stable; names are not identifiers. Use semantic versions for published dataset/schema contracts where compatibility matters, immutable IDs for artifacts/reports, and content checksums for dataset manifests.

## Multimodal and scientific data
The catalog describes payloads; it does not force them into relational columns. Scientific-field profiles may include mesh/topology, variables, units, coordinate system, time steps, boundary conditions, solver/version, numerical settings and field arrays. Video profiles may include segments, frame indexes, audio tracks, annotations and alignment metadata.

## Interoperability
Prefer JSON Schema, Parquet/Arrow, W3C PROV concepts, SPDX or equivalent license identifiers, and immutable environment digests where suitable. Do not claim standards compliance until conformance tests exist.
