"""PostgreSQL image assets and durable generation jobs."""

from psycopg_pool import AsyncConnectionPool

from .errors import ImageNotFound


class ImageStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def setup(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_image_jobs (
                    job_id text PRIMARY KEY,
                    user_id bigint NOT NULL,
                    thread_id uuid NOT NULL REFERENCES agent_threads(thread_id) ON DELETE CASCADE,
                    prompt text NOT NULL,
                    size text NOT NULL,
                    reference_image_ids text[] NOT NULL,
                    request_key text NOT NULL,
                    provider_task_id text,
                    status text NOT NULL CHECK (
                        status IN ('queued', 'submitting', 'running', 'succeeded', 'failed', 'uncertain')
                    ),
                    error text,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    UNIQUE (thread_id, request_key)
                )
            """)
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS agent_image_jobs_queued
                ON agent_image_jobs(created_at, job_id) WHERE status = 'queued'
            """)
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS agent_image_jobs_thread
                ON agent_image_jobs(thread_id, created_at, job_id)
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_image_assets (
                    image_id text PRIMARY KEY,
                    user_id bigint NOT NULL,
                    thread_id uuid NOT NULL REFERENCES agent_threads(thread_id) ON DELETE CASCADE,
                    name text NOT NULL,
                    media_type text NOT NULL,
                    width integer NOT NULL,
                    height integer NOT NULL,
                    source text NOT NULL CHECK (source IN ('upload', 'generated')),
                    path text NOT NULL,
                    job_id text REFERENCES agent_image_jobs(job_id) ON DELETE CASCADE,
                    created_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS agent_image_assets_thread
                ON agent_image_assets(thread_id, created_at, image_id)
            """)

    @staticmethod
    async def _lock_thread(connection, thread_id, user_id: int) -> None:
        cursor = await connection.execute(
            "SELECT 1 FROM agent_threads WHERE thread_id = %s AND user_id = %s FOR UPDATE",
            (thread_id, user_id),
        )
        if await cursor.fetchone() is None:
            raise ImageNotFound("对话不存在。")

    @staticmethod
    async def _insert_asset(connection, asset: dict) -> dict:
        cursor = await connection.execute(
            """INSERT INTO agent_image_assets
               (image_id, user_id, thread_id, name, media_type, width, height, source, path, job_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (asset["image_id"], asset["user_id"], asset["thread_id"], asset["name"],
             asset["media_type"], asset["width"], asset["height"], asset["source"],
             asset["path"], asset.get("job_id")),
        )
        return await cursor.fetchone()

    async def add_asset(self, asset: dict) -> dict:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                await self._lock_thread(connection, asset["thread_id"], asset["user_id"])
                return await self._insert_asset(connection, asset)

    async def get_asset(self, image_id: str, user_id: int, thread_id=None) -> dict:
        query = "SELECT * FROM agent_image_assets WHERE image_id = %s AND user_id = %s"
        parameters = (image_id, user_id)
        if thread_id is not None:
            query += " AND thread_id = %s"
            parameters += (thread_id,)
        async with self.pool.connection() as connection:
            cursor = await connection.execute(query, parameters)
            row = await cursor.fetchone()
        if row is None:
            raise ImageNotFound("图片不存在。")
        return row

    async def list_assets(self, thread_id, user_id: int) -> list[dict]:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT * FROM agent_image_assets WHERE thread_id = %s AND user_id = %s
                   ORDER BY created_at, image_id""", (thread_id, user_id),
            )
            return await cursor.fetchall()

    async def create_job(
        self, *, job_id: str, user_id: int, thread_id, prompt: str, size: str,
        reference_image_ids: list[str], request_key: str,
    ) -> dict:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                await self._lock_thread(connection, thread_id, user_id)
                if reference_image_ids:
                    cursor = await connection.execute(
                        """SELECT image_id FROM agent_image_assets
                           WHERE image_id = ANY(%s) AND user_id = %s AND thread_id = %s""",
                        (reference_image_ids, user_id, thread_id),
                    )
                    found = {row["image_id"] for row in await cursor.fetchall()}
                    if found != set(reference_image_ids):
                        raise ImageNotFound("参考图片不存在或不属于当前对话。")
                cursor = await connection.execute(
                    """INSERT INTO agent_image_jobs
                       (job_id, user_id, thread_id, prompt, size, reference_image_ids, request_key, status)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')
                       ON CONFLICT (thread_id, request_key)
                       DO UPDATE SET request_key = EXCLUDED.request_key RETURNING *""",
                    (job_id, user_id, thread_id, prompt, size, reference_image_ids, request_key),
                )
                return await cursor.fetchone()

    async def get_job(self, job_id: str, user_id: int) -> dict:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM agent_image_jobs WHERE job_id = %s AND user_id = %s",
                (job_id, user_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ImageNotFound("图片任务不存在。")
        return row

    async def job_assets(self, job_id: str, user_id: int) -> list[dict]:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT * FROM agent_image_assets WHERE job_id = %s AND user_id = %s
                   ORDER BY created_at, image_id""", (job_id, user_id),
            )
            return await cursor.fetchall()

    async def list_jobs(self, thread_id, user_id: int) -> list[dict]:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT job_id FROM agent_image_jobs WHERE thread_id = %s AND user_id = %s
                   ORDER BY created_at, job_id""", (thread_id, user_id),
            )
            return await cursor.fetchall()

    async def claim_job(self) -> dict | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute("""
                UPDATE agent_image_jobs SET status = 'submitting', updated_at = now()
                WHERE job_id = (
                    SELECT job_id FROM agent_image_jobs WHERE status = 'queued'
                    ORDER BY created_at, job_id FOR UPDATE SKIP LOCKED LIMIT 1
                ) RETURNING *
            """)
            return await cursor.fetchone()

    async def mark_running(self, job_id: str, provider_task_id: str) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """UPDATE agent_image_jobs SET status = 'running', provider_task_id = %s,
                   error = NULL, updated_at = now() WHERE job_id = %s AND status = 'submitting'""",
                (provider_task_id, job_id),
            )

    async def pending_jobs(self) -> list[dict]:
        async with self.pool.connection() as connection:
            cursor = await connection.execute("""
                SELECT * FROM agent_image_jobs WHERE status = 'running'
                ORDER BY created_at, job_id
            """)
            return await cursor.fetchall()

    async def finish_job(self, job_id: str, asset: dict) -> None:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                await self._insert_asset(connection, asset)
                await connection.execute(
                    """UPDATE agent_image_jobs SET status = 'succeeded', error = NULL,
                       updated_at = now() WHERE job_id = %s AND status = 'running'""", (job_id,),
                )

    async def fail_job(self, job_id: str, error: str, uncertain: bool = False) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """UPDATE agent_image_jobs SET status = %s, error = %s, updated_at = now()
                   WHERE job_id = %s""", ("uncertain" if uncertain else "failed", error, job_id),
            )

    async def record_poll_error(self, job_id: str, error: str) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """UPDATE agent_image_jobs SET error = %s, updated_at = now()
                   WHERE job_id = %s AND status = 'running'""", (error, job_id),
            )

    async def recover_submitting(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute("""
                UPDATE agent_image_jobs SET status = 'uncertain',
                    error = '服务在提交图片任务时中断，结果尚未确认，请勿重复提交。', updated_at = now()
                WHERE status = 'submitting'
            """)

    async def has_active_jobs(self, thread_id, user_id: int) -> bool:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT 1 FROM agent_image_jobs WHERE thread_id = %s AND user_id = %s
                   AND status IN ('queued', 'submitting', 'running') LIMIT 1""", (thread_id, user_id),
            )
            return await cursor.fetchone() is not None

    async def delete_thread_data(self, thread_id, user_id: int) -> None:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                await self._lock_thread(connection, thread_id, user_id)
                await connection.execute(
                    "DELETE FROM agent_image_assets WHERE thread_id = %s AND user_id = %s",
                    (thread_id, user_id),
                )
                await connection.execute(
                    "DELETE FROM agent_image_jobs WHERE thread_id = %s AND user_id = %s",
                    (thread_id, user_id),
                )
