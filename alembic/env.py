"""
Alembic migration environment.

The database URL and the target schema both come from the application itself
(app/config.py -> app/database.py -> app/models.py), so migrations always run
against the same connection settings the API uses. Nothing DB-related is
configured in alembic.ini.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Import the app's engine URL and full model metadata. `app.models` must be
# imported so every table is registered on Base.metadata before autogenerate
# compares it against the live database.
from app.database import DATABASE_URL, Base
from app import models  # noqa: F401 - registers all tables on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url():
    """
    The app's real connection URL, unless ALEMBIC_DATABASE_URL overrides it
    (useful for CI, a staging DB, or building the baseline migration against a
    throwaway database). Returned as a URL object / string that never passes
    through configparser, so a '%' in the password is not treated as
    interpolation syntax.
    """
    override = os.environ.get("ALEMBIC_DATABASE_URL")
    return override or DATABASE_URL


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it (alembic upgrade --sql)."""
    context.configure(
        url=str(_get_url()),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = create_engine(_get_url(), poolclass=pool.NullPool)

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
