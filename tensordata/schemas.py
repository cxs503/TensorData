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
    # Approval is intentionally not accepted from an asset producer.
    rights_status: Literal["unknown", "restricted", "review_required", "prohibited"] = "unknown"
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


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    owner: str = Field(min_length=1, max_length=255)
    intended_uses: list[str] = Field(default_factory=list)


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    owner: str
    intended_uses: list[str]
    created_at: datetime


class DatasetMemberInput(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=36)
    role: str = Field(default="data", min_length=1, max_length=64)
    selector: dict[str, Any] = Field(default_factory=dict)


class DatasetVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
    members: list[DatasetMemberInput] = Field(min_length=1)
    split_definition: dict[str, Any] = Field(default_factory=dict)
    schema_refs: list[str] = Field(default_factory=list)
    transform_refs: list[str] = Field(default_factory=list)
    created_by: str = Field(min_length=1, max_length=255)


class DatasetVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    version: str
    manifest_json: dict[str, Any]
    manifest_sha256: str
    created_by: str
    created_at: datetime


class ProvenanceCreate(BaseModel):
    activity_type: str = Field(min_length=1, max_length=128)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    outputs: list[dict[str, Any]] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    responsible_actor: str = Field(min_length=1, max_length=255)
    code_digest: str | None = Field(default=None, max_length=128)
    environment_digest: str | None = Field(default=None, max_length=128)


class ProvenanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    activity_type: str
    inputs_json: list[dict[str, Any]]
    outputs_json: list[dict[str, Any]]
    parameters_json: dict[str, Any]
    responsible_actor: str
    code_digest: str | None
    environment_digest: str | None
    created_at: datetime
