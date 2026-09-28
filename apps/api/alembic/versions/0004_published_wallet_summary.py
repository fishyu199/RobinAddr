"""Add bounded leaderboard summaries to published wallets.

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("published_wallets")}
    if "summary" not in columns:
        op.add_column(
            "published_wallets",
            sa.Column(
                "summary",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    op.execute(
        """
        UPDATE published_wallets
        SET summary = jsonb_build_object(
            'win_rate', metrics->'win_rate',
            'copy_loss_rate', metrics->'copy_loss_rate',
            'avg_profit_loss_ratio', metrics->'avg_profit_loss_ratio',
            'trading_days', metrics->'trading_days',
            'recent_20_stats', metrics->'recent_20_stats',
            'tokens_traded', metrics->'tokens_traded',
            'trading_volume', metrics->'trading_volume',
            'avg_invest_per_token', metrics->'avg_invest_per_token',
            'median_holding_time_seconds', metrics->'median_holding_time_seconds',
            'target_daily_pnl_14d', metrics->'target_daily_pnl_14d',
            'copy_daily_pnl_14d', metrics->'copy_daily_pnl_14d',
            'last_active', metrics->'last_active'
        )
        WHERE summary = '{}'::jsonb
        """
    )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("published_wallets")}
    if "summary" in columns:
        op.drop_column("published_wallets", "summary")
