"""Add immutable artifact quality reports.

Revision ID: 0002_quality_reports
Revises: 0001_initial
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_quality_reports"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quality_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("data_artifacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("ruleset_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("findings_json", sa.JSON(), nullable=False),
        sa.Column("executed_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_quality_reports_artifact_id", "quality_reports", ["artifact_id"])
    op.create_index("ix_quality_reports_status", "quality_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_quality_reports_status", table_name="quality_reports")
    op.drop_index("ix_quality_reports_artifact_id", table_name="quality_reports")
    op.drop_table("quality_reports")
