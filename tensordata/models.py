from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class DataAsset(Base):
    __tablename__ = "data_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="quarantine", index=True)
    provenance_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    rights_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    allowed_purposes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    artifacts: Mapped[list["DataArtifact"]] = relationship(back_populates="asset", cascade="all, delete-orphan")


class DataArtifact(Base):
    __tablename__ = "data_artifacts"
    __table_args__ = (UniqueConstraint("asset_id", "sha256", name="uq_asset_artifact_sha256"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    asset_id: Mapped[str] = mapped_column(ForeignKey("data_assets.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="raw")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    asset: Mapped[DataAsset] = relationship(back_populates="artifacts")


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    intended_uses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    versions: Mapped[list["DatasetVersion"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    dataset: Mapped[Dataset] = relationship(back_populates="versions")


class ProvenanceRecord(Base):
    __tablename__ = "provenance_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    activity_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    inputs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    outputs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    parameters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    responsible_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    code_digest: Mapped[str | None] = mapped_column(String(128))
    environment_digest: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
