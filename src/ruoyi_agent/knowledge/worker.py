"""Single managed worker for durable PostgreSQL ingestion/deletion jobs."""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import load_knowledge_settings
from .parser import parse_document
from .service import remove_directory
from .splitting import split_document
from .store import KnowledgeNotFound, KnowledgeStore
from .vectorstore import KnowledgeVectorStore


logger = logging.getLogger(__name__)
READY_FILE = Path(__file__).resolve().parents[3] / ".runtime" / "knowledge-worker.ready"


class KnowledgeWorker:
    def __init__(self, store, vectors, settings):
        self.store, self.vectors, self.settings = store, vectors, settings

    async def process(self, job: dict) -> None:
        if job["kind"] == "index":
            await self.index(job)
        elif job["kind"] == "delete_document":
            await self.delete_document(job["document_id"])
        elif job["kind"] == "delete_base":
            for document_id in await self.store.base_document_ids(job["kb_id"]):
                await self.vectors.delete_document(document_id)
            await asyncio.to_thread(remove_directory, self.settings.data_dir / job["kb_id"], self.settings.data_dir)
            await self.store.delete_base_metadata(job["kb_id"])
        else:
            raise ValueError(f"未知知识库任务类型：{job['kind']}")

    async def index(self, job: dict) -> None:
        try:
            document = await self.store.get_document(job["document_id"])
        except KnowledgeNotFound:
            return  # An earlier queued deletion removed this document.
        version = job["version"]
        if document["status"] != "processing" or document["version"] != version:
            return
        document_id, kb_id = document["document_id"], document["kb_id"]
        output_dir = self.settings.data_dir / kb_id / document_id / str(version)
        await self.vectors.delete_document(document_id)
        await self.store.set_stage(document_id, version, "parsing")
        parsed = await parse_document(self.settings.data_dir / document["original_path"], output_dir, self.settings)
        await self.store.set_stage(document_id, version, "splitting")
        chunks = split_document(parsed, kb_id=kb_id, document_id=document_id, version=version,
                                document_name=document["name"], chunk_size=self.settings.chunk_size,
                                chunk_overlap=self.settings.chunk_overlap)
        if not chunks:
            raise ValueError("文档没有可建立索引的文本，请检查原文件或识别结果。")
        await self.store.set_stage(document_id, version, "indexing")
        await self.vectors.add_documents(chunks)
        assets = [{"asset_id": asset.asset_id, "document_id": document_id, "version": version,
                   "path": asset.path.relative_to(self.settings.data_dir).as_posix(),
                   "media_type": asset.media_type, "page": asset.page} for asset in parsed.assets]
        published = await self.store.complete_index(document_id, version, assets, len(chunks))
        if not published:
            await self.vectors.delete_document(document_id, version)
            return
        for directory in output_dir.parent.iterdir():
            if directory.is_dir() and directory.name.isdigit() and directory != output_dir:
                await asyncio.to_thread(remove_directory, directory, self.settings.data_dir)

    async def delete_document(self, document_id: str) -> None:
        try:
            document = await self.store.get_document(document_id)
        except KnowledgeNotFound:
            return
        await self.vectors.delete_document(document_id)
        await asyncio.to_thread(remove_directory,
                                self.settings.data_dir / document["kb_id"] / document_id,
                                self.settings.data_dir)
        await self.store.delete_document_metadata(document_id)

    async def run_once(self) -> bool:
        job = await self.store.claim_job()
        if job is None:
            return False
        try:
            await self.process(job)
        except Exception as exc:
            # A failed external job is recorded for explicit retry; keep serving other jobs.
            error = f"{type(exc).__name__}: {exc}"
            for secret in (self.settings.mineru_api_token, self.settings.milvus_token):
                if secret:
                    error = error.replace(secret, "[redacted]")
            logger.error("Knowledge job %s failed: %s", job["job_id"], error[:1000])
            await self.store.fail_job(job, error[:1000])
        else:
            await self.store.finish_job(job["job_id"])
        return True


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    settings = load_knowledge_settings()
    async with AsyncConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=3,
                                  kwargs={"autocommit": True, "row_factory": dict_row,
                                          "prepare_threshold": 0}, timeout=10) as pool:
        await pool.wait()
        store = KnowledgeStore(pool)
        await store.setup()
        await store.recover_jobs()
        vectors = KnowledgeVectorStore(settings)
        worker = KnowledgeWorker(store, vectors, settings)
        READY_FILE.parent.mkdir(parents=True, exist_ok=True)
        READY_FILE.write_text(str(os.getpid()), encoding="ascii")
        try:
            while True:
                if not await worker.run_once():
                    await asyncio.sleep(1)
        finally:
            READY_FILE.unlink(missing_ok=True)
            await vectors.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from ruoyi_agent.server import loop_factory
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(main())
