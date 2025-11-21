from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db import base  # noqa: F401  # ensure models are imported for metadata

engine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.exec_driver_sql(
            "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS sort_order DOUBLE PRECISION NOT NULL DEFAULT 0"
        )
        await conn.exec_driver_sql(
            """
            WITH ordered AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY created_at, id) AS rn
                FROM tasks
            )
            UPDATE tasks
            SET sort_order = ordered.rn
            FROM ordered
            WHERE tasks.id = ordered.id
              AND (tasks.sort_order = 0 OR tasks.sort_order IS NULL)
            """
        )
        await conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_base64 TEXT")
        await conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(2048)")
