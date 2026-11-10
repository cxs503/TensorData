from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
