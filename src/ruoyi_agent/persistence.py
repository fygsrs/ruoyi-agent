"""Application-owned conversations and the ledger for approved Java writes."""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Awaitable, Callable
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


class ConversationBusy(Exception):
    """Another request is already running in this conversation."""


class PostgresStore:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool
        self._locks: dict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def setup(self):
        async with self.pool.connection() as connection:
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_threads (
                    thread_id uuid PRIMARY KEY,
                    user_id bigint NOT NULL,
                    title text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS agent_threads_user_updated
                ON agent_threads (user_id, updated_at DESC)
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_operations (
                    operation_id text PRIMARY KEY,
                    user_id bigint NOT NULL,
                    operation text NOT NULL,
                    fields jsonb NOT NULL,
                    status text NOT NULL CHECK (
                        status IN ('executing', 'succeeded', 'failed', 'uncertain')
                    ),
                    result jsonb,
                    error text,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)

    async def create_thread(self, thread_id: UUID, user_id: int, title: str):
        async with self.pool.connection() as connection:
            await connection.execute(
                "INSERT INTO agent_threads (thread_id, user_id, title) VALUES (%s, %s, %s)",
                (thread_id, user_id, title),
            )

    async def owns_thread(self, thread_id: UUID, user_id: int) -> bool:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM agent_threads WHERE thread_id = %s AND user_id = %s",
                (thread_id, user_id),
            )
            return await cursor.fetchone() is not None

    async def list_threads(self, user_id: int):
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT thread_id, title, updated_at FROM agent_threads
                   WHERE user_id = %s ORDER BY updated_at DESC LIMIT 100""", (user_id,)
            )
            return await cursor.fetchall()

    async def touch(self, thread_id: UUID, title: str | None = None):
        async with self.pool.connection() as connection:
            await connection.execute(
                """UPDATE agent_threads SET updated_at = now(),
                   title = CASE WHEN title = '新对话' AND %s::text IS NOT NULL THEN %s ELSE title END
                   WHERE thread_id = %s""", (title, title, thread_id)
            )

    async def delete_thread(self, thread_id: UUID, user_id: int):
        async with self.pool.connection() as connection:
            await connection.execute(
                "DELETE FROM agent_threads WHERE thread_id = %s AND user_id = %s",
                (thread_id, user_id),
            )

    @asynccontextmanager
    async def lock(self, thread_id: UUID):
        # Shared by requests in this process's event loop. An uncontended
        # acquire does not suspend, so busy requests cannot pass this check.
        lock = self._locks[thread_id]
        if lock.locked():
            raise ConversationBusy
        try:
            async with lock:
                yield
        finally:
            del self._locks[thread_id]

    async def lookup(self, operation_id: str, user_id: int) -> dict | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT operation, status, result, error FROM agent_operations "
                "WHERE operation_id = %s AND user_id = %s", (operation_id, user_id)
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        if row["status"] == "succeeded":
            return row["result"]
        if row["status"] == "failed":
            message = row["error"]
        else:
            message = "该操作的执行结果尚未确认，请在若依用户管理中核查；系统不会自动重复提交。"
        return {"executed": False, "operation": row["operation"], "message": message,
                "status": row["status"]}

    async def execute(self, operation_id: str, user_id: int, operation: str,
                      payload: dict, execute_callback: Callable[[], Awaitable[dict]]) -> dict:
        from ruoyi_agent.ruoyi_client import RuoYiError

        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """INSERT INTO agent_operations (operation_id,user_id,operation,fields,status)
                   VALUES (%s,%s,%s,%s,'executing') ON CONFLICT DO NOTHING RETURNING operation_id""",
                (operation_id, user_id, operation, Jsonb(payload)),
            )
            inserted = await cursor.fetchone()
        if inserted is None:
            return await self.lookup(operation_id, user_id)
        try:
            result = await execute_callback()
        except RuoYiError as exc:
            status = "uncertain" if exc.uncertain else "failed"
            async with self.pool.connection() as connection:
                await connection.execute(
                    """UPDATE agent_operations SET status=%s, error=%s, updated_at=now()
                       WHERE operation_id=%s""", (status, str(exc), operation_id)
                )
            raise
        async with self.pool.connection() as connection:
            await connection.execute(
                """UPDATE agent_operations SET status='succeeded', result=%s, updated_at=now()
                   WHERE operation_id=%s""", (Jsonb(result), operation_id)
            )
        return result
