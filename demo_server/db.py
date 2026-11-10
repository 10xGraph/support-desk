"""The asyncpg connection pool. `connect()` and `init_db()` run in the app's lifespan."""

import os
from pathlib import Path

import asyncpg


pool: asyncpg.Pool | None = None


async def connect() -> None:
    global pool  # noqa: PLW0603
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=5)


async def init_db() -> None:
    """Create the demo schema and tables and insert the dummy data, if missing."""
    await pool.execute((Path(__file__).parent / "schema.sql").read_text())


async def close() -> None:
    global pool  # noqa: PLW0603
    if pool is not None:
        await pool.close()
        pool = None
