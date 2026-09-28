"""Store GMGN ranking metrics on candidate wallets.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("candidate_wallets")}
    if "discovery_metrics" in columns:
        return
    op.add_column(
        "candidate_wallets",
        sa.Column(
            "discovery_metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("candidate_wallets")}
    if "discovery_metrics" in columns:
        op.drop_column("candidate_wallets", "discovery_metrics")
