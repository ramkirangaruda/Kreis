from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)

from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # PgBouncer in transaction pooling mode does not support server-side
    # prepared statements. Disabling asyncpg's statement cache (and giving each
    # prepared statement a unique name) makes the app safe behind PgBouncer;
    # it is harmless when connecting straight to Postgres.
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session