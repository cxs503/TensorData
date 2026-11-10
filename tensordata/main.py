from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import os

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, engine, get_db
from .models import DataArtifact, DataAsset
from .schemas import AssetCreate, AssetRead, ArtifactRead


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    get_settings().storage_root.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="TensorData API",
    version="0.1.0",
    description="Governed data-asset registry and artifact service.",
    lifespan=lifespan,
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if not expected:
        raise HTTPException(status_code=503, detail="API access is disabled: configure TENSORDATA_API_KEY")
    if x_api_key is None or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.get("/health")
def health():
    return {"status": "ok", "service": "tensordata", "version": app.version}


@app.post("/api/v1/assets", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(payload: AssetCreate, _: None = Depends(require_api_key), db: Session = Depends(get_db)):
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


@app.get("/api/v1/assets", response_model=list[AssetRead], dependencies=[Depends(require_api_key)])
def list_assets(
    asset_type: str | None = None,
    lifecycle_state: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 500 or offset < 0:
        raise HTTPException(status_code=422, detail="limit must be 1..500 and offset >= 0")
    query = select(DataAsset).order_by(DataAsset.created_at.desc()).offset(offset).limit(limit)
    if asset_type:
        query = query.where(DataAsset.asset_type == asset_type)
    if lifecycle_state:
        query = query.where(DataAsset.lifecycle_state == lifecycle_state)
    return list(db.scalars(query).all())


@app.get("/api/v1/assets/{asset_id}", response_model=AssetRead, dependencies=[Depends(require_api_key)])
def get_asset(asset_id: str, db: Session = Depends(get_db)):
    asset = db.get(DataAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@app.post("/api/v1/assets/{asset_id}/artifacts", response_model=ArtifactRead, status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    asset_id: str,
    file: UploadFile = File(...),
    role: str = "raw",
    _: None = Depends(require_api_key),
    db: Session = Depends(get_db),
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


@app.get("/api/v1/assets/{asset_id}/artifacts", response_model=list[ArtifactRead], dependencies=[Depends(require_api_key)])
def list_artifacts(asset_id: str, db: Session = Depends(get_db)):
    if db.get(DataAsset, asset_id) is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return list(db.scalars(select(DataArtifact).where(DataArtifact.asset_id == asset_id).order_by(DataArtifact.created_at)).all())
