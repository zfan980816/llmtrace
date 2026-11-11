"""teams: multi-tenant teams, users/projects belong to a team"""
import secrets
import uuid

import sqlalchemy as sa
from alembic import op

revision = "h9i0j1k2l3m4"
down_revision = "f7a8c9d0e1b2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("invite_code", sa.String(16), nullable=False, unique=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.add_column("users", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_index("ix_users_team", "users", ["team_id"])
    op.add_column("projects", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_index("ix_projects_team", "projects", ["team_id"])

    # 现有数据归入默认团队：admin 与全部存量项目；其余邮箱注册用户保持无团队（登录后自行创建/加入）
    conn = op.get_bind()
    admin_id = conn.execute(sa.text("select id from users order by created_at limit 1")).scalar()
    if admin_id is None:
        return
    team_id = str(uuid.uuid4())
    conn.execute(
        sa.text("insert into teams (id, name, invite_code, created_by, created_at) "
                "values (:id, :name, :code, :by, CURRENT_TIMESTAMP)"),
        {"id": team_id, "name": "LLMTrace", "code": secrets.token_hex(4), "by": admin_id},
    )
    conn.execute(sa.text("update users set team_id=:t where role='admin'"), {"t": team_id})
    conn.execute(sa.text("update projects set team_id=:t"), {"t": team_id})


def downgrade():
    op.drop_index("ix_projects_team", table_name="projects")
    op.drop_column("projects", "team_id")
    op.drop_index("ix_users_team", table_name="users")
    op.drop_column("users", "team_id")
    op.drop_table("teams")
