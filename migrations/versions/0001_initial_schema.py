"""Initial TensorData metadata schema.

Revision ID: 0001_initial
Revises:
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("asset_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("lifecycle_state", sa.String(32), nullable=False),
        sa.Column("provenance_status", sa.String(32), nullable=False),
        sa.Column("rights_status", sa.String(32), nullable=False),
        sa.Column("allowed_purposes", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("name", "asset_type", "lifecycle_state"):
        op.create_index(f"ix_data_assets_{column}", "data_assets", [column])

    op.create_table(
        "data_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("data_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("asset_id", "sha256", name="uq_asset_artifact_sha256"),
    )
    op.create_index("ix_data_artifacts_asset_id", "data_artifacts", ["asset_id"])

    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("intended_uses", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_datasets_name", "datasets", ["name"])

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),
    )
    op.create_index("ix_dataset_versions_dataset_id", "dataset_versions", ["dataset_id"])

    op.create_table(
        "provenance_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("activity_type", sa.String(128), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("outputs_json", sa.JSON(), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("responsible_actor", sa.String(255), nullable=False),
        sa.Column("code_digest", sa.String(128)),
        sa.Column("environment_digest", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provenance_records_activity_type", "provenance_records", ["activity_type"])


def downgrade() -> None:
    op.drop_index("ix_provenance_records_activity_type", table_name="provenance_records")
    op.drop_table("provenance_records")
    op.drop_index("ix_dataset_versions_dataset_id", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index("ix_datasets_name", table_name="datasets")
    op.drop_table("datasets")
    op.drop_index("ix_data_artifacts_asset_id", table_name="data_artifacts")
    op.drop_table("data_artifacts")
    for column in ("lifecycle_state", "asset_type", "name"):
        op.drop_index(f"ix_data_assets_{column}", table_name="data_assets")
    op.drop_table("data_assets")
