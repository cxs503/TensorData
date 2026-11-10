import csv
import json
import os
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, engine, get_db
from .models import (
    DataArtifact,
    DataAsset,
    Dataset,
    DatasetVersion,
    ProvenanceRecord,
    QualityReport,
)
from .schemas import (
    ArtifactRead,
    AssetCreate,
    AssetRead,
    DatasetCreate,
    DatasetRead,
    DatasetVersionCreate,
    DatasetVersionRead,
    ProvenanceCreate,
    ProvenanceRead,
    QualityCheckCreate,
    QualityReportRead,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if get_settings().auto_create_schema:
        Base.metadata.create_all(bind=engine)
    get_settings().storage_root.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="TensorData API",
    version="0.2.0",
    description="Governed data-asset registry, immutable dataset manifests, and provenance service.",
    lifespan=lifespan,
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if not expected:
        raise HTTPException(status_code=503, detail="API access is disabled: configure TENSORDATA_API_KEY")
    if x_api_key is None or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


DB_DEPENDENCY = Depends(get_db)
AUTH_DEPENDENCY = Depends(require_api_key)
UPLOAD_FILE = File(...)


@app.get("/health")
def health():
    return {"status": "ok", "service": "tensordata", "version": app.version}


@app.post("/api/v1/assets", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(
    payload: AssetCreate,
    _: None = AUTH_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    asset = DataAsset(
        name=payload.name,
        asset_type=payload.asset_type,
        description=payload.description,
        owner=payload.owner,
        rights_status=payload.rights_status,
        allowed_purposes=payload.allowed_purposes,
        metadata_json={**payload.metadata, **({"source_ref": payload.source_ref} if payload.source_ref else {})},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@app.get("/api/v1/assets", response_model=list[AssetRead], dependencies=[AUTH_DEPENDENCY])
def list_assets(
    asset_type: str | None = None,
    lifecycle_state: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = DB_DEPENDENCY,
):
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1..500 and offset >= 0")
    query = select(DataAsset).order_by(DataAsset.created_at.desc()).offset(offset).limit(limit)
    if asset_type:
        query = query.where(DataAsset.asset_type == asset_type)
    if lifecycle_state:
        query = query.where(DataAsset.lifecycle_state == lifecycle_state)
    return list(db.scalars(query).all())


@app.get("/api/v1/assets/{asset_id}", response_model=AssetRead, dependencies=[AUTH_DEPENDENCY])
def get_asset(asset_id: str, db: Session = DB_DEPENDENCY):
    asset = db.get(DataAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@app.post(
    "/api/v1/assets/{asset_id}/artifacts",
    response_model=ArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_artifact(
    asset_id: str,
    file: UploadFile = UPLOAD_FILE,
    role: str = "raw",
    _: None = AUTH_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    asset = db.get(DataAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    settings = get_settings()
    root = settings.storage_root
    digest = sha256()
    temp_path = root / f".upload-{uuid4().hex}.tmp"
    size = 0
    try:
        with temp_path.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="Upload exceeds configured size limit")
                digest.update(chunk)
                out.write(chunk)
        checksum = digest.hexdigest()

        existing = db.scalar(
            select(DataArtifact).where(
                DataArtifact.asset_id == asset_id,
                DataArtifact.sha256 == checksum,
            )
        )
        if existing is not None:
            temp_path.unlink(missing_ok=True)
            return existing

        destination = root / checksum[:2] / checksum
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            temp_path.unlink(missing_ok=True)
        else:
            os.replace(temp_path, destination)

        artifact = DataArtifact(
            asset_id=asset_id,
            role=role,
            filename=Path(file.filename or "unnamed").name[:255],
            media_type=file.content_type or "application/octet-stream",
            size_bytes=size,
            sha256=checksum,
            storage_uri=destination.as_uri(),
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        return artifact
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get(
    "/api/v1/assets/{asset_id}/artifacts",
    response_model=list[ArtifactRead],
    dependencies=[AUTH_DEPENDENCY],
)
def list_artifacts(asset_id: str, db: Session = DB_DEPENDENCY):
    if db.get(DataAsset, asset_id) is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return list(
        db.scalars(
            select(DataArtifact)
            .where(DataArtifact.asset_id == asset_id)
            .order_by(DataArtifact.created_at)
        ).all()
    )


@app.get("/api/v1/artifacts/{artifact_id}/content", dependencies=[AUTH_DEPENDENCY])
def download_artifact(artifact_id: str, db: Session = DB_DEPENDENCY):
    artifact = db.get(DataArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    parsed = urlparse(artifact.storage_uri)
    if parsed.scheme != "file":
        raise HTTPException(status_code=501, detail="This storage backend cannot serve local downloads")
    payload_path = Path(unquote(parsed.path)).resolve()
    storage_root = get_settings().storage_root.resolve()
    if not payload_path.is_relative_to(storage_root) or not payload_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact payload is missing")

    return FileResponse(
        payload_path,
        media_type=artifact.media_type,
        filename=artifact.filename,
        headers={"ETag": f'"{artifact.sha256}"', "X-Content-SHA256": artifact.sha256},
    )


@app.post(
    "/api/v1/artifacts/{artifact_id}/quality-checks",
    response_model=QualityReportRead,
    status_code=status.HTTP_201_CREATED,
)
def run_quality_checks(
    artifact_id: str,
    payload: QualityCheckCreate,
    _: None = AUTH_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    artifact = db.get(DataArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    parsed = urlparse(artifact.storage_uri)
    if parsed.scheme != "file":
        raise HTTPException(status_code=501, detail="Quality checks currently require local file storage")
    file_path = Path(unquote(parsed.path)).resolve()
    storage_root = get_settings().storage_root.resolve()
    if not file_path.is_relative_to(storage_root) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact payload is missing")

    findings = []
    actual_hash = sha256()
    actual_size = 0
    with file_path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            actual_hash.update(chunk)
            actual_size += len(chunk)
    checksum_matches = actual_hash.hexdigest() == artifact.sha256
    if actual_size == 0:
        findings.append({"rule_id": "file.non_empty", "severity": "error", "message": "Artifact is empty"})
    if actual_size != artifact.size_bytes:
        findings.append({"rule_id": "file.size_matches_metadata", "severity": "error", "message": "Stored size differs from metadata"})
    if not checksum_matches:
        findings.append({"rule_id": "file.sha256_matches_metadata", "severity": "error", "message": "Stored checksum differs from metadata"})

    summary = {"size_bytes": actual_size, "sha256_verified": checksum_matches}
    if payload.profile == "tabular":
        try:
            with file_path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                headers = reader.fieldnames or []
                rows = list(reader)
                if not headers or any(not header.strip() for header in headers):
                    findings.append({"rule_id": "tabular.header_present", "severity": "error", "message": "CSV must have non-empty column headers"})
                if not rows:
                    findings.append({"rule_id": "tabular.rows_present", "severity": "error", "message": "CSV contains no data rows"})
                missing_cells = sum(1 for row in rows for value in row.values() if value is None or not str(value).strip())
                signatures = [tuple((value or "").strip() for value in row.values()) for row in rows]
                duplicate_rows = len(signatures) - len(set(signatures))
                if missing_cells:
                    findings.append({"rule_id": "tabular.missing_cells", "severity": "warning", "count": missing_cells, "message": "Missing or blank cells detected"})
                if duplicate_rows:
                    findings.append({"rule_id": "tabular.duplicate_rows", "severity": "warning", "count": duplicate_rows, "message": "Duplicate rows detected"})
                summary.update({
                    "row_count": len(rows),
                    "column_count": len(headers),
                    "columns": headers,
                    "missing_cells": missing_cells,
                    "duplicate_rows": duplicate_rows,
                })
        except (UnicodeDecodeError, csv.Error) as exc:
            findings.append({"rule_id": "tabular.csv_parseable", "severity": "error", "message": f"CSV parsing failed: {exc}"})

    failed = any(item["severity"] == "error" for item in findings)
    report = QualityReport(
        artifact_id=artifact.id,
        artifact_sha256=artifact.sha256,
        profile=payload.profile,
        ruleset_version="0.1.0",
        status="failed" if failed else "passed",
        summary_json=summary,
        findings_json=findings,
        executed_by=payload.executed_by,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@app.get(
    "/api/v1/artifacts/{artifact_id}/quality-reports",
    response_model=list[QualityReportRead],
    dependencies=[AUTH_DEPENDENCY],
)
def list_quality_reports(artifact_id: str, db: Session = DB_DEPENDENCY):
    if db.get(DataArtifact, artifact_id) is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    query = (
        select(QualityReport)
        .where(QualityReport.artifact_id == artifact_id)
        .order_by(QualityReport.created_at.desc())
    )
    return list(db.scalars(query).all())


@app.post("/api/v1/datasets", response_model=DatasetRead, status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: DatasetCreate,
    _: None = AUTH_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    dataset = Dataset(
        name=payload.name,
        description=payload.description,
        owner=payload.owner,
        intended_uses=payload.intended_uses,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


@app.get("/api/v1/datasets", response_model=list[DatasetRead], dependencies=[AUTH_DEPENDENCY])
def list_datasets(limit: int = 100, offset: int = 0, db: Session = DB_DEPENDENCY):
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1..500 and offset >= 0")
    query = select(Dataset).order_by(Dataset.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(query).all())


@app.post(
    "/api/v1/datasets/{dataset_id}/versions",
    response_model=DatasetVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset_version(
    dataset_id: str,
    payload: DatasetVersionCreate,
    _: None = AUTH_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    existing_version = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version == payload.version,
        )
    )
    if existing_version is not None:
        raise HTTPException(status_code=409, detail="Dataset version already exists and is immutable")

    artifact_ids = [member.artifact_id for member in payload.members]
    if len(set(artifact_ids)) != len(artifact_ids):
        raise HTTPException(status_code=422, detail="A dataset version cannot contain duplicate artifact IDs")

    artifacts = list(db.scalars(select(DataArtifact).where(DataArtifact.id.in_(artifact_ids))).all())
    artifact_by_id = {artifact.id: artifact for artifact in artifacts}
    missing = sorted(set(artifact_ids) - set(artifact_by_id))
    if missing:
        raise HTTPException(status_code=422, detail={"unknown_artifact_ids": missing})

    manifest_members = []
    for member in payload.members:
        artifact = artifact_by_id[member.artifact_id]
        asset = db.get(DataAsset, artifact.asset_id)
        if asset.rights_status == "prohibited":
            raise HTTPException(
                status_code=422,
                detail=f"Artifact {artifact.id} belongs to an asset prohibited from dataset assembly",
            )
        latest_quality = db.scalar(
            select(QualityReport)
            .where(QualityReport.artifact_id == artifact.id)
            .order_by(QualityReport.created_at.desc())
        )
        if latest_quality is None or latest_quality.artifact_sha256 != artifact.sha256:
            raise HTTPException(
                status_code=422,
                detail=f"Artifact {artifact.id} has no quality report for its current content",
            )
        if latest_quality.status != "passed":
            raise HTTPException(
                status_code=422,
                detail=f"Artifact {artifact.id} failed its latest quality check",
            )
        manifest_members.append({
            "artifact_id": artifact.id,
            "asset_id": artifact.asset_id,
            "asset_type": asset.asset_type,
            "artifact_sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "media_type": artifact.media_type,
            "role": member.role,
            "selector": member.selector,
            "rights_status_at_snapshot": asset.rights_status,
            "lifecycle_state_at_snapshot": asset.lifecycle_state,
        })

    manifest = {
        "manifest_schema": "tensordata.dataset-manifest.v1",
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "version": payload.version,
        "members": manifest_members,
        "split_definition": payload.split_definition,
        "schema_refs": payload.schema_refs,
        "transform_refs": payload.transform_refs,
    }
    canonical_manifest = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest_digest = sha256(canonical_manifest.encode("utf-8")).hexdigest()

    dataset_version = DatasetVersion(
        dataset_id=dataset_id,
        version=payload.version,
        manifest_json=manifest,
        manifest_sha256=manifest_digest,
        created_by=payload.created_by,
    )
    db.add(dataset_version)
    db.commit()
    db.refresh(dataset_version)
    return dataset_version


@app.get(
    "/api/v1/datasets/{dataset_id}/versions",
    response_model=list[DatasetVersionRead],
    dependencies=[AUTH_DEPENDENCY],
)
def list_dataset_versions(dataset_id: str, db: Session = DB_DEPENDENCY):
    if db.get(Dataset, dataset_id) is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    query = (
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.created_at.desc())
    )
    return list(db.scalars(query).all())


@app.get(
    "/api/v1/datasets/{dataset_id}/versions/{version}",
    response_model=DatasetVersionRead,
    dependencies=[AUTH_DEPENDENCY],
)
def get_dataset_version(dataset_id: str, version: str, db: Session = DB_DEPENDENCY):
    result = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version == version,
        )
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Dataset version not found")
    return result


@app.post(
    "/api/v1/provenance",
    response_model=ProvenanceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_provenance(
    payload: ProvenanceCreate,
    _: None = AUTH_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    record = ProvenanceRecord(
        activity_type=payload.activity_type,
        inputs_json=payload.inputs,
        outputs_json=payload.outputs,
        parameters_json=payload.parameters,
        responsible_actor=payload.responsible_actor,
        code_digest=payload.code_digest,
        environment_digest=payload.environment_digest,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@app.get(
    "/api/v1/provenance",
    response_model=list[ProvenanceRead],
    dependencies=[AUTH_DEPENDENCY],
)
def list_provenance(
    activity_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = DB_DEPENDENCY,
):
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1..500 and offset >= 0")
    query = select(ProvenanceRecord).order_by(ProvenanceRecord.created_at.desc()).offset(offset).limit(limit)
    if activity_type:
        query = query.where(ProvenanceRecord.activity_type == activity_type)
    return list(db.scalars(query).all())
