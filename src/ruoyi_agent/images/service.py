"""Owned image assets and generation jobs; no application usage quotas."""

import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from ruoyi_agent.knowledge.service import remove_directory
from .config import ImageSettings
from .errors import ImageConflict
from .files import MAX_IMAGE_BYTES, image_info
from .store import ImageStore


def asset_info(asset: dict) -> dict:
    return {name: asset[name] for name in ("image_id", "name", "media_type", "width", "height", "source")}


class ImageService:
    def __init__(self, store: ImageStore, settings: ImageSettings):
        self.store, self.settings = store, settings

    async def upload(self, thread_id: str, user_id: int, file: UploadFile) -> dict:
        data = await file.read(MAX_IMAGE_BYTES + 1)
        media_type, suffix, width, height = await asyncio.to_thread(image_info, data)
        image_id = str(uuid4())
        relative = Path(thread_id) / (image_id + suffix)
        path = self.settings.data_dir / relative
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        saved = False
        try:
            await asyncio.to_thread(path.write_bytes, data)
            asset = await self.store.add_asset({
                "image_id": image_id, "user_id": user_id, "thread_id": thread_id,
                "name": (Path(file.filename or "参考图片").name[:250] or "参考图片"),
                "media_type": media_type, "width": width, "height": height,
                "source": "upload", "path": relative.as_posix(), "job_id": None,
            })
            saved = True
            return asset_info(asset)
        finally:
            if not saved:
                await asyncio.to_thread(path.unlink, missing_ok=True)

    async def selected_assets(self, image_ids: list[str], user_id: int, thread_id: str) -> list[dict]:
        return [asset_info(await self.store.get_asset(image_id, user_id, thread_id)) for image_id in image_ids]

    async def context_assets(self, thread_id: str, user_id: int) -> tuple[dict, ...]:
        return tuple(asset_info(asset) for asset in await self.store.list_assets(thread_id, user_id))

    async def create_job(self, *, user_id: int, thread_id: str, prompt: str, size: str,
                         reference_image_ids: list[str], request_key: str) -> dict:
        return await self.store.create_job(job_id=str(uuid4()), user_id=user_id, thread_id=thread_id,
                                           prompt=prompt, size=size, reference_image_ids=reference_image_ids,
                                           request_key=request_key)

    async def job(self, job_id: str, user_id: int) -> dict:
        job = await self.store.get_job(job_id, user_id)
        return {**{key: job[key] for key in ("job_id", "status", "prompt", "size", "error", "reference_image_ids")},
                "images": [asset_info(asset) for asset in await self.store.job_assets(job_id, user_id)]}

    async def delete_thread(self, thread_id: str, user_id: int) -> None:
        if await self.store.has_active_jobs(thread_id, user_id):
            raise ImageConflict("当前会话还有图片正在生成，请任务完成后再删除。")
        await asyncio.to_thread(remove_directory, self.settings.data_dir / thread_id, self.settings.data_dir)
        await self.store.delete_thread_data(thread_id, user_id)

    async def restore_jobs(self, messages: list[dict], thread_id: str, user_id: int) -> list[dict]:
        known_ids = {artifact["job_id"] for message in messages for artifact in message.get("artifacts", [])
                     if artifact["type"] == "image_generation"}
        # A paid task can be committed before the tool's graph checkpoint. The
        # durable job table keeps its card accessible after a disconnect/restart.
        for job in await self.store.list_jobs(thread_id, user_id):
            if job["job_id"] not in known_ids:
                messages.append({"role": "assistant", "content": "", "artifacts": [
                    {"type": "image_generation", "job_id": job["job_id"]}]})
        return messages
