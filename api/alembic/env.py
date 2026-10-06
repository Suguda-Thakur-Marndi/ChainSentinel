from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

# Import application settings and SQLAlchemy Base metadata
import app.models  # Registers all domain entities with Base.metadata
from app.core.config import settings
from app.db.base import Base


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    import os
    x_args = context.get_x_argument(as_dictionary=True)
    url = x_args.get("url") or settings.DATABASE_URL or os.environ.get("DATABASE_URL")
    if url and url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    import os
    x_args = context.get_x_argument(as_dictionary=True)
    url = x_args.get("url") or settings.DATABASE_URL or os.environ.get("DATABASE_URL")
    if url and url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    configuration = config.get_section(config.config_ini_section) or {}
    if url:
        configuration["sqlalchemy.url"] = url

    connect_args = {}
    if url and not str(url).startswith("sqlite"):
        connect_args["connect_timeout"] = 5

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
