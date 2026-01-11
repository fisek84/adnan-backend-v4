from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# this is the Alembic Config object, which provides access to the values within
# the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# -------------------------------------------------------------------
# ENTERPRISE: read DATABASE_URL from environment and override ini value
# -------------------------------------------------------------------
db_url = (os.getenv("DATABASE_URL") or "").strip()
if not db_url:
    raise RuntimeError(
        "DATABASE_URL is not set in the environment. "
        "Example: postgresql+psycopg://admin:password@localhost:5432/alignment_db"
    )

# Override sqlalchemy.url early to avoid configparser interpolation issues
config.set_main_option("sqlalchemy.url", db_url)

# Add your model's MetaData object here for 'autogenerate' support.
# target_metadata = mymodel.Base.metadata
#
# NOTE: trenutno Base/modeli za Outcome Feedback Loop jos nisu dodani -> NIJE POZNATO.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
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
    """Run migrations in 'online' mode."""
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
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
