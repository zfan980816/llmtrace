"""langgraph "model" node is a chain, not an llm call

Revision ID: p3q4r5s6t7u8
Revises: n2o3p4q5r6s7
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = "p3q4r5s6t7u8"
down_revision = "n2o3p4q5r6s7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧版接入层把 LangGraph 的 model 图节点记成了 llm span（没有模型名也没有 token），
    # 导致模型调用量翻倍。这里改回 chain，和当前接入逻辑保持一致。
    op.execute(sa.text(
        "UPDATE spans SET span_type = 'chain' "
        "WHERE span_type = 'llm' AND LOWER(name) = 'model' "
        "AND COALESCE(model, '') = '' AND COALESCE(total_tokens, 0) = 0"
    ))


def downgrade() -> None:
    # 数据修正不可逆：无法区分哪些 model span 是旧逻辑误分类的
    pass
