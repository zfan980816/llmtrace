"""add users.must_change_password

Revision ID: m1n2o3p4q5r6
Revises: k1l2m3n4o5p6
Create Date: 2026-11-11
"""
from alembic import op
import sqlalchemy as sa

revision = "m1n2o3p4q5r6"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
