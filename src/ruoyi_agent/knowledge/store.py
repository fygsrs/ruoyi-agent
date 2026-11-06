"""PostgreSQL knowledge metadata and the durable queue for one managed worker."""

from uuid import uuid4

from psycopg_pool import AsyncConnectionPool


class KnowledgeNotFound(Exception):
    """The requested knowledge resource is unavailable."""


class KnowledgeConflict(Exception):
    """The requested change conflicts with a resource's current state."""


class KnowledgeStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def setup(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_knowledge_bases (
                    kb_id text PRIMARY KEY,
                    name text NOT NULL,
                    description text NOT NULL,
                    created_by bigint NOT NULL,
                    status text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'deleting', 'delete_failed')),
                    error text,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_knowledge_docs (
                    document_id text PRIMARY KEY,
                    kb_id text NOT NULL REFERENCES agent_knowledge_bases(kb_id) ON DELETE CASCADE,
                    name text NOT NULL,
                    size bigint NOT NULL,
                    media_type text NOT NULL,
                    original_path text NOT NULL,
                    created_by bigint NOT NULL,
                    version integer NOT NULL DEFAULT 1,
                    status text NOT NULL CHECK (
                        status IN ('processing', 'ready', 'failed', 'deleting', 'delete_failed')
                    ),
                    stage text NOT NULL,
                    error text,
                    chunk_count integer NOT NULL DEFAULT 0,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS agent_knowledge_docs_base_created
                ON agent_knowledge_docs(kb_id, created_at DESC)
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_knowledge_assets (
                    asset_id text PRIMARY KEY,
                    document_id text NOT NULL REFERENCES agent_knowledge_docs(document_id) ON DELETE CASCADE,
                    version integer NOT NULL,
                    path text NOT NULL,
                    media_type text NOT NULL,
                    page integer
                )
            """)
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS agent_knowledge_assets_document
                ON agent_knowledge_assets(document_id)
            """)
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_knowledge_jobs (
                    job_id text PRIMARY KEY,
                    kind text NOT NULL CHECK (kind IN ('index', 'delete_document', 'delete_base')),
                    document_id text,
                    kb_id text NOT NULL,
                    version integer,
                    status text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
                    error text,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            await connection.execute("""
                CREATE INDEX IF NOT EXISTS agent_knowledge_jobs_queued
                ON agent_knowledge_jobs(created_at, job_id) WHERE status = 'queued'
            """)

    async def get_base(self, kb_id: str) -> dict:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM agent_knowledge_bases WHERE kb_id = %s", (kb_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise KnowledgeNotFound("知识库不存在。")
        return row

    async def list_bases(self) -> list[dict]:
        async with self.pool.connection() as connection:
            cursor = await connection.execute("""
                SELECT b.*, count(d.document_id) AS document_count
                FROM agent_knowledge_bases b
                LEFT JOIN agent_knowledge_docs d ON d.kb_id = b.kb_id
                GROUP BY b.kb_id ORDER BY b.created_at DESC
            """)
            return await cursor.fetchall()

    async def create_base(
        self, kb_id: str, name: str, description: str, user_id: int
    ) -> dict:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """INSERT INTO agent_knowledge_bases(kb_id, name, description, created_by)
                   VALUES (%s, %s, %s, %s) RETURNING *""",
                (kb_id, name, description, user_id),
            )
            return await cursor.fetchone()

    async def update_base(self, kb_id: str, name: str, description: str) -> dict:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    "SELECT * FROM agent_knowledge_bases WHERE kb_id = %s FOR UPDATE", (kb_id,)
                )
                row = await cursor.fetchone()
                if row is None:
                    raise KnowledgeNotFound("知识库不存在。")
                if row["status"] != "active":
                    raise KnowledgeConflict("知识库正在删除，无法修改。")
                cursor = await connection.execute(
                    """UPDATE agent_knowledge_bases SET name = %s, description = %s,
                       updated_at = now() WHERE kb_id = %s RETURNING *""",
                    (name, description, kb_id),
                )
                return await cursor.fetchone()

    async def list_documents(self, kb_id: str, page: int, page_size: int) -> dict:
        await self.get_base(kb_id)
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT count(*) AS total FROM agent_knowledge_docs WHERE kb_id = %s", (kb_id,)
            )
            total = (await cursor.fetchone())["total"]
            cursor = await connection.execute(
                """SELECT * FROM agent_knowledge_docs WHERE kb_id = %s
                   ORDER BY created_at DESC, document_id LIMIT %s OFFSET %s""",
                (kb_id, page_size, (page - 1) * page_size),
            )
            return {"items": await cursor.fetchall(), "total": total}

    async def get_document(self, document_id: str) -> dict:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM agent_knowledge_docs WHERE document_id = %s", (document_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise KnowledgeNotFound("文档不存在。")
        return row

    async def create_document(
        self, *, document_id: str, kb_id: str, name: str, size: int,
        media_type: str, original_path: str, created_by: int,
    ) -> dict:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    "SELECT status FROM agent_knowledge_bases WHERE kb_id = %s FOR UPDATE", (kb_id,)
                )
                base = await cursor.fetchone()
                if base is None:
                    raise KnowledgeNotFound("知识库不存在。")
                if base["status"] != "active":
                    raise KnowledgeConflict("知识库正在删除，无法上传文档。")
                cursor = await connection.execute(
                    """INSERT INTO agent_knowledge_docs
                       (document_id, kb_id, name, size, media_type, original_path, created_by, status, stage)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'processing', 'queued') RETURNING *""",
                    (document_id, kb_id, name, size, media_type, original_path, created_by),
                )
                document = await cursor.fetchone()
                await connection.execute(
                    """INSERT INTO agent_knowledge_jobs
                       (job_id, kind, document_id, kb_id, version, status)
                       VALUES (%s, 'index', %s, %s, 1, 'queued')""",
                    (str(uuid4()), document_id, kb_id),
                )
                return document

    async def reprocess_document(self, document_id: str) -> dict:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    """SELECT d.*, b.status AS base_status FROM agent_knowledge_bases b
                       JOIN agent_knowledge_docs d ON d.kb_id = b.kb_id
                       WHERE d.document_id = %s FOR UPDATE OF b, d""", (document_id,)
                )
                document = await cursor.fetchone()
                if document is None:
                    raise KnowledgeNotFound("文档不存在。")
                if document["base_status"] != "active" or document["status"] not in ("ready", "failed"):
                    raise KnowledgeConflict("仅已完成或失败的文档可以重新处理。")
                cursor = await connection.execute(
                    """UPDATE agent_knowledge_docs SET version = version + 1, status = 'processing',
                       stage = 'queued', error = NULL, chunk_count = 0, updated_at = now()
                       WHERE document_id = %s RETURNING *""", (document_id,)
                )
                document = await cursor.fetchone()
                await connection.execute(
                    """INSERT INTO agent_knowledge_jobs
                       (job_id, kind, document_id, kb_id, version, status)
                       VALUES (%s, 'index', %s, %s, %s, 'queued')""",
                    (str(uuid4()), document_id, document["kb_id"], document["version"]),
                )
                return document

    async def request_delete_document(self, document_id: str) -> dict:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    "SELECT * FROM agent_knowledge_docs WHERE document_id = %s FOR UPDATE", (document_id,)
                )
                document = await cursor.fetchone()
                if document is None:
                    raise KnowledgeNotFound("文档不存在。")
                if document["status"] == "deleting":
                    return document
                cursor = await connection.execute(
                    """UPDATE agent_knowledge_docs SET status = 'deleting', stage = 'queued',
                       error = NULL, updated_at = now() WHERE document_id = %s RETURNING *""",
                    (document_id,),
                )
                document = await cursor.fetchone()
                await connection.execute(
                    """INSERT INTO agent_knowledge_jobs(job_id, kind, document_id, kb_id, status)
                       VALUES (%s, 'delete_document', %s, %s, 'queued')""",
                    (str(uuid4()), document_id, document["kb_id"]),
                )
                return document

    async def request_delete_base(self, kb_id: str) -> dict:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    "SELECT * FROM agent_knowledge_bases WHERE kb_id = %s FOR UPDATE", (kb_id,)
                )
                base = await cursor.fetchone()
                if base is None:
                    raise KnowledgeNotFound("知识库不存在。")
                if base["status"] == "deleting":
                    return base
                cursor = await connection.execute(
                    """UPDATE agent_knowledge_bases SET status = 'deleting', error = NULL,
                       updated_at = now() WHERE kb_id = %s RETURNING *""", (kb_id,)
                )
                base = await cursor.fetchone()
                await connection.execute(
                    """UPDATE agent_knowledge_docs SET status = 'deleting', stage = 'queued',
                       error = NULL, updated_at = now() WHERE kb_id = %s""", (kb_id,)
                )
                await connection.execute(
                    """INSERT INTO agent_knowledge_jobs(job_id, kind, kb_id, status)
                       VALUES (%s, 'delete_base', %s, 'queued')""", (str(uuid4()), kb_id)
                )
                return base

    async def recover_jobs(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """UPDATE agent_knowledge_jobs SET status = 'queued', updated_at = now()
                   WHERE status = 'running'"""
            )

    async def claim_job(self) -> dict | None:
        async with self.pool.connection() as connection:
            cursor = await connection.execute("""
                UPDATE agent_knowledge_jobs SET status = 'running', updated_at = now()
                WHERE job_id = (
                    SELECT job_id FROM agent_knowledge_jobs WHERE status = 'queued'
                    ORDER BY created_at, job_id FOR UPDATE SKIP LOCKED LIMIT 1
                ) RETURNING *
            """)
            return await cursor.fetchone()

    async def set_stage(self, document_id: str, version: int, stage: str) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """UPDATE agent_knowledge_docs SET stage = %s, updated_at = now()
                   WHERE document_id = %s AND version = %s AND status = 'processing'""",
                (stage, document_id, version),
            )

    async def complete_index(
        self, document_id: str, version: int, assets: list[dict], chunk_count: int
    ) -> bool:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                cursor = await connection.execute(
                    """SELECT d.document_id FROM agent_knowledge_bases b
                       JOIN agent_knowledge_docs d ON d.kb_id = b.kb_id
                       WHERE d.document_id = %s AND d.version = %s
                         AND d.status = 'processing' AND b.status = 'active'
                       FOR UPDATE OF b, d""", (document_id, version)
                )
                if await cursor.fetchone() is None:
                    return False
                await connection.execute(
                    "DELETE FROM agent_knowledge_assets WHERE document_id = %s", (document_id,)
                )
                for asset in assets:
                    await connection.execute(
                        """INSERT INTO agent_knowledge_assets
                           (asset_id, document_id, version, path, media_type, page)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (asset["asset_id"], document_id, version, asset["path"], asset["media_type"], asset["page"]),
                    )
                await connection.execute(
                    """UPDATE agent_knowledge_docs SET status = 'ready', stage = 'ready',
                       error = NULL, chunk_count = %s, updated_at = now() WHERE document_id = %s""",
                    (chunk_count, document_id),
                )
                return True

    async def get_asset(self, asset_id: str) -> dict:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """SELECT a.*, d.kb_id FROM agent_knowledge_assets a
                   JOIN agent_knowledge_docs d ON d.document_id = a.document_id AND d.version = a.version
                   JOIN agent_knowledge_bases b ON b.kb_id = d.kb_id
                   WHERE a.asset_id = %s AND d.status = 'ready' AND b.status = 'active'""", (asset_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise KnowledgeNotFound("知识库图片不存在或文档尚未就绪。")
        return row

    async def ready_document_ids(self, kb_ids: list[str] | None = None) -> list[str]:
        return list(await self.ready_document_versions(kb_ids))

    async def base_document_ids(self, kb_id: str) -> list[str]:
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT document_id FROM agent_knowledge_docs WHERE kb_id = %s", (kb_id,)
            )
            return [row["document_id"] for row in await cursor.fetchall()]

    async def ready_document_versions(self, kb_ids: list[str] | None = None) -> dict[str, int]:
        parameters = ()
        sql = """SELECT d.document_id, d.version FROM agent_knowledge_docs d
                 JOIN agent_knowledge_bases b ON b.kb_id = d.kb_id
                 WHERE d.status = 'ready' AND b.status = 'active'"""
        if kb_ids is not None:
            sql += " AND d.kb_id = ANY(%s)"
            parameters = (kb_ids,)
        async with self.pool.connection() as connection:
            cursor = await connection.execute(sql, parameters)
            return {row["document_id"]: row["version"] for row in await cursor.fetchall()}

    async def delete_document_metadata(self, document_id: str) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                "DELETE FROM agent_knowledge_docs WHERE document_id = %s", (document_id,)
            )

    async def delete_base_metadata(self, kb_id: str) -> None:
        async with self.pool.connection() as connection:
            await connection.execute("DELETE FROM agent_knowledge_bases WHERE kb_id = %s", (kb_id,))

    async def finish_job(self, job_id: str) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """UPDATE agent_knowledge_jobs SET status = 'succeeded', error = NULL,
                   updated_at = now() WHERE job_id = %s""", (job_id,)
            )

    async def fail_job(self, job: dict, error: str) -> None:
        async with self.pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    """UPDATE agent_knowledge_jobs SET status = 'failed', error = %s,
                       updated_at = now() WHERE job_id = %s""", (error, job["job_id"])
                )
                if job["kind"] == "index":
                    await connection.execute(
                        """UPDATE agent_knowledge_docs SET status = 'failed', stage = 'failed',
                           error = %s, updated_at = now() WHERE document_id = %s
                           AND version = %s AND status = 'processing'""",
                        (error, job["document_id"], job["version"]),
                    )
                elif job["kind"] == "delete_document":
                    await connection.execute(
                        """UPDATE agent_knowledge_docs SET status = 'delete_failed', stage = 'failed',
                           error = %s, updated_at = now() WHERE document_id = %s AND status = 'deleting'""",
                        (error, job["document_id"]),
                    )
                else:
                    await connection.execute(
                        """UPDATE agent_knowledge_bases SET status = 'delete_failed', error = %s,
                           updated_at = now() WHERE kb_id = %s AND status = 'deleting'""", (error, job["kb_id"])
                    )
                    await connection.execute(
                        """UPDATE agent_knowledge_docs SET status = 'delete_failed', stage = 'failed',
                           error = %s, updated_at = now() WHERE kb_id = %s AND status = 'deleting'""",
                        (error, job["kb_id"]),
                    )
