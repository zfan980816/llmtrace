"""Alembic 迁移环境：URL 来自环境变量，元数据来自 app.models。"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 必须在导入 app.* 之前固定 URL：
# 1) 迁移专用 ALEMBIC_DATABASE_URL 优先
# 2) 否则跟随应用 DATABASE_URL
# 3) 都没有时回落本地 sqlite（开发场景），避免 import app.database 时
#    因默认 postgres URL 缺少驱动而报错
if os.environ.get("ALEMBIC_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["ALEMBIC_DATABASE_URL"]
os.environ.setdefault("DATABASE_URL", "sqlite:///./llmtrace.db")

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
from app import models  # noqa: E402,F402  (确保所有表注册到 metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ["DATABASE_URL"]
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=db_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=db_url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
