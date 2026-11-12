"""add traces.share_token

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-11-12
"""
from alembic import op
import sqlalchemy as sa

revision = "n2o3p4q5r6s7"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("traces", sa.Column("share_token", sa.String(64), nullable=True))
    op.create_index("ix_traces_share_token", "traces", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_traces_share_token", table_name="traces")
    op.drop_column("traces", "share_token")
