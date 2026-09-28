"""Track serial analysis batches.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "analysis_batches" not in tables:
        op.create_table(
            "analysis_batches",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("requested_count", sa.Integer(), nullable=False),
            sa.Column("total_count", sa.Integer(), nullable=False),
            sa.Column("completed_count", sa.Integer(), nullable=False),
            sa.Column("failed_count", sa.Integer(), nullable=False),
            sa.Column("skipped_count", sa.Integer(), nullable=False),
            sa.Column("current_address", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_analysis_batches_status", "analysis_batches", ["status"])

    inspector = sa.inspect(op.get_bind())
    run_columns = {column["name"] for column in inspector.get_columns("analysis_runs")}
    if "batch_id" not in run_columns:
        op.add_column(
            "analysis_runs",
            sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_analysis_runs_batch_id",
            "analysis_runs",
            "analysis_batches",
            ["batch_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_analysis_runs_batch_id", "analysis_runs", ["batch_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "analysis_runs" in inspector.get_table_names():
        run_columns = {column["name"] for column in inspector.get_columns("analysis_runs")}
        if "batch_id" in run_columns:
            op.drop_index("ix_analysis_runs_batch_id", table_name="analysis_runs")
            op.drop_constraint("fk_analysis_runs_batch_id", "analysis_runs", type_="foreignkey")
            op.drop_column("analysis_runs", "batch_id")
    if "analysis_batches" in inspector.get_table_names():
        op.drop_index("ix_analysis_batches_status", table_name="analysis_batches")
        op.drop_table("analysis_batches")
