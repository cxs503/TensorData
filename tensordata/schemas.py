from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AssetType = Literal[
    "document", "table", "image", "audio", "video", "timeseries", "spatial",
    "point_cloud", "mesh", "scientific_field", "knowledge_bundle", "agent_trace",
    "training_sample", "model_artifact", "other",
]


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    asset_type: AssetType
    description: str | None = None
    owner: str = Field(min_length=1, max_length=255)
    source_ref: str | None = None
    rights_status: Literal["unknown", "restricted", "review_required", "approved", "prohibited"] = "unknown"
    allowed_purposes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    asset_type: str
    description: str | None
    owner: str
    lifecycle_state: str
    provenance_status: str
    rights_status: str
    allowed_purposes: list[str]
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_id: str
    role: str
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    storage_uri: str
    created_at: datetime
