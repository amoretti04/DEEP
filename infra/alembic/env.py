"""Alembic environment configured for async SQLAlchemy.

DB URL is read from ``DATABASE_URL`` at runtime; the ``sqlalchemy.url``
in alembic.ini is a fallback for local dev.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import models so autogenerate sees them
from infra.alembic.orm import Base  # noqa: F401  (registers metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Prefer env var
if (url := os.getenv("DATABASE_URL")) is not None:
    config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Translate async URL to sync for alembic's sync engine runs.
    url = config.get_main_option("sqlalchemy.url") or ""
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        config.set_main_option("sqlalchemy.url", url)

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
