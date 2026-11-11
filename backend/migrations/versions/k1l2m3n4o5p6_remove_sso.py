"""remove sso login (feishu/oidc/github)"""
import sqlalchemy as sa
from alembic import op

revision = "k1l2m3n4o5p6"
down_revision = "h9i0j1k2l3m4"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_user_sso", table_name="users")
    op.drop_column("users", "sso_provider")
    op.drop_column("users", "sso_subject")


def downgrade():
    op.add_column("users", sa.Column("sso_subject", sa.String(128), nullable=True))
    op.add_column("users", sa.Column("sso_provider", sa.String(32), nullable=True))
    op.create_index("ix_user_sso", "users", ["sso_provider", "sso_subject"], unique=True)
