"""Alembic environment.

Reads ``DATABASE_URL`` from the environment if set, otherwise falls back to
the ``sqlalchemy.url`` from ``alembic.ini``. Uses
:data:`src.storage.models.Base.metadata` as the autogenerate target.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.storage.models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    return config.get_main_option("sqlalchemy.url")


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
