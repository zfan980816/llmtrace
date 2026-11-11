"""email login"""
import sqlalchemy as sa
from alembic import op

revision = "f7a8c9d0e1b2"
down_revision = "deec300e41bc"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email", sa.String(120), nullable=True))
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.execute("update users set email = username where username like '%@%' and email is null")


def downgrade():
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "email")
