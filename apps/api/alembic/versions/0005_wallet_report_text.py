"""Store the latest wallet report alongside its analysis metrics.

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("published_wallets")}
    if "report_text" not in columns:
        op.add_column("published_wallets", sa.Column("report_text", sa.Text(), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("published_wallets")}
    if "report_text" in columns:
        op.drop_column("published_wallets", "report_text")
