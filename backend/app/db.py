from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _normalize_db_url(url: str) -> str:
    # Render (and many hosted Postgres providers) hand out 'postgres://' URLs,
    # but SQLAlchemy 2.x requires the explicit driver-qualified form.
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


_settings = get_settings()
engine = create_async_engine(_normalize_db_url(_settings.db_url), echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def _add_missing_columns(sync_conn) -> None:
    """Add columns that exist on the models but not yet in the database.

    There's no migration tool here, and create_all() only creates whole missing
    tables — it never alters an existing one. Without this, adding a column to a
    model breaks every database created before that column existed.

    A column is only safe to add in place if existing rows can be given a value:
    either it's nullable, or it carries a server_default the database can backfill
    with. A NOT NULL column with neither would fail against a populated table, and
    that case deserves a real migration rather than a guess here.
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.schema import CreateColumn

    inspector = sa_inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all already built it with every column
        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            if not column.nullable and column.server_default is None:
                continue
            ddl = CreateColumn(column).compile(dialect=sync_conn.dialect)
            sync_conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}')


async def init_db() -> None:
    # Import models so they register on Base.metadata before create_all runs.
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
