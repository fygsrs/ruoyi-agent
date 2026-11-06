"""Manage originals and queue durable knowledge processing jobs."""

import asyncio
import mimetypes
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import UploadFile

from .config import KnowledgeSettings
from .parser import SUPPORTED_EXTENSIONS
from .store import KnowledgeStore
from .vectorstore import KnowledgeVectorStore


class UploadRejected(ValueError):
    pass


class KnowledgeService:
    def __init__(self, store: KnowledgeStore, vectors: KnowledgeVectorStore, settings: KnowledgeSettings):
        self.store = store
        self.vectors = vectors
        self.settings = settings

    async def upload(self, kb_id: str, file: UploadFile, user_id: int) -> dict:
        name = Path(file.filename or "").name
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise UploadRejected("不支持此文件格式，请上传 PDF、Office、图片或 UTF-8 文本。")
        if len(name) > 255:
            raise UploadRejected("文件名不能超过 255 个字符。")
        document_id = str(uuid4())
        relative_path = Path(kb_id) / document_id / f"original{suffix}"
        target = self.settings.data_dir / relative_path
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        # If saving or queueing fails, remove this newly allocated directory.
        queued = False
        try:
            size = 0
            with target.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise UploadRejected("文件不能超过 50 MB。")
                    await asyncio.to_thread(output.write, chunk)
            if size == 0:
                raise UploadRejected("不能上传空文件。")
            document = await self.store.create_document(
                document_id=document_id, kb_id=kb_id, name=name, size=size,
                media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
                original_path=relative_path.as_posix(), created_by=user_id,
            )
            queued = True
            return document
        finally:
            if not queued:
                await asyncio.to_thread(remove_directory, target.parent, self.settings.data_dir)

    async def search(self, query: str):
        document_ids = await self.store.ready_document_ids(None)
        matches = await self.vectors.search(query, None, document_ids)
        # Deletion or reprocessing may have started during the external search.
        current_versions = await self.store.ready_document_versions(None)
        return [document for document in matches
                if current_versions.get(document.metadata["document_id"]) == document.metadata["version"]]


def remove_directory(path: Path, root: Path) -> None:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    if resolved == root.resolve():
        raise ValueError("拒绝删除知识库根目录。")
    if resolved.exists():
        shutil.rmtree(resolved)
