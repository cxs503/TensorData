# Data Governance, Quality and Release Policy

## Governing principle
Collection is not permission to use. Every asset must carry source, rights, purpose, provenance and quality status appropriate to its risk. Unknown rights are not approved rights.

## Minimum registration
Before use beyond quarantine, record source and acquisition time; acquiring actor and method; rights/license status and terms; permitted purposes and restrictions; checksum and payload metadata; sensitivity and retention; owner/steward and lifecycle state. Unknown or conflicting rights remain restricted.

## Quality dimensions
Select rules by asset type and intended use:
- completeness, validity and schema conformance
- uniqueness and duplication
- consistency across records and sources
- accuracy against source or independent reference
- timeliness and staleness
- representativeness and coverage
- provenance completeness and integrity
- scientific plausibility and domain constraints
- annotation/alignment quality for multimodal data

An aggregate score must not hide critical failures. Reports expose rule-level results, severity, evidence and thresholds.

## Lifecycle gates
- Quarantine: newly acquired, unreviewed or rights-unclear.
- Registered: minimum metadata and source record complete.
- Profiled: basic statistics and schema findings available.
- Validated: required rules pass or exceptions are documented.
- Approved: rights and quality approvals satisfied for specified purposes.
- Published: immutable version available to authorized consumers.
- Deprecated/withdrawn: superseded, expired, revoked or defective.

Publication is purpose-specific. An asset may be approved for research inspection but not training or redistribution.

## Separation of duties
The producer must not be sole approver of a high-impact dataset. Combine deterministic checks, independent agent review and human/domain expert review when required. Agreement among language models is not proof of truth.

## Synthetic data
Record generated status, generator/model/tool version, parameters/specification, parent assets, provenance, validation and limitations. Never silently mix synthetic and observed/experimental evidence.

## Scientific data controls
Record units, coordinate systems, initial/boundary conditions, solver/version, numerical settings, mesh/discretization, convergence indicators and benchmark validation where applicable. Domain projects supply domain-specific validators.

## Access, privacy and retention
Enforce least privilege, purpose limitation, access audit and retention/deletion obligations. Never store credentials in metadata. Sensitive/personal data requires minimization and appropriate review.

## Release evidence
A published dataset version includes manifest, schema, quality report, provenance and rights summaries, checksums, version and reproducibility notes. Narrative reports alone are insufficient.


## Rights and licensing manifest (mandatory)

Every external, mixed-origin, or distributable asset must have a machine-readable rights manifest under `rights/manifests/`. A dataset-level license is not inferred from the repository's software license.

Minimum controls:

- Preserve the original source URI, source title/provider, acquisition timestamp, acquisition method and accountable actor.
- Record the exact SPDX license expression where known. Use `NOASSERTION` only to express that the license is not established; it is not an approval.
- Record rights holder, evidence URI and evidence checksum where available, attribution text, restrictions, permitted and prohibited purposes, and whether redistribution, commercial use and model training are allowed.
- Distinguish `unknown`, `needs_review`, `restricted`, `approved` and `prohibited` rights states. Only `approved` assets may pass a purpose-specific release gate.
- An approval must identify the reviewer, review time, evidence and approved purposes. A license label alone is not sufficient evidence that the uploader had authority to grant it.
- Derived assets inherit applicable restrictions from their inputs unless a documented legal basis establishes otherwise. Transformations do not automatically remove copyright, database rights, privacy, confidentiality or contractual restrictions.
- Keep raw evidence and rights evidence immutable and checksummed. If terms change or permission is revoked, withdraw or re-evaluate affected dataset versions.

The repository's manifest validator is a minimum structural gate, not a legal opinion or a substitute for human rights review. See `rights/README.md` and `scripts/check_rights_manifests.py`.
