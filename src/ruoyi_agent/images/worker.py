"""Submit durable image jobs once and resume polling known provider tasks."""

import asyncio
from io import BytesIO
import logging
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from dotenv import load_dotenv
import httpx
from PIL import Image, UnidentifiedImageError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .errors import ImageInputError, ImageNotFound, ImageProviderError, SubmissionUncertain
from .store import ImageStore


logger = logging.getLogger(__name__)
READY_FILE = Path(__file__).resolve().parents[3] / ".runtime" / "image-worker.ready"


def write_generated_image(data: bytes, target: Path) -> tuple[int, int]:
    """Validate provider bytes and publish a complete PNG on local disk."""
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            width, height = image.size
            rendered = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageInputError("图片服务返回了无法读取的图片。") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    try:
        rendered.save(temporary, format="PNG")
        temporary.replace(target)
    finally:
        rendered.close()
        temporary.unlink(missing_ok=True)
    return width, height


class ImageWorker:
    def __init__(self, store, provider, settings):
        self.store, self.provider, self.settings = store, provider, settings

    def error_text(self, error: Exception) -> str:
        message = f"{type(error).__name__}: {error}"
        if self.settings.api_key:
            message = message.replace(self.settings.api_key, "[redacted]")
        return message[:1000]

    async def submit(self, job: dict) -> None:
        references = []
        try:
            for image_id in job["reference_image_ids"]:
                asset = await self.store.get_asset(image_id, job["user_id"], job["thread_id"])
                path = self.settings.data_dir / asset["path"]
                references.append(path)
            provider_task_id = await self.provider.submit(job["prompt"], job["size"], references)
        except SubmissionUncertain as exc:
            error = self.error_text(exc)
            logger.warning("Image submission %s is uncertain: %s", job["job_id"], error)
            await self.store.fail_job(job["job_id"], error, uncertain=True)
        except (ImageInputError, ImageNotFound, ImageProviderError) as exc:
            error = self.error_text(exc)
            logger.warning("Image submission %s failed: %s", job["job_id"], error)
            await self.store.fail_job(job["job_id"], error)
        else:
            # Persist the paid task ID before polling, without holding a DB connection
            # during the HTTP request. A crash before this write stays uncertain.
            await self.store.mark_running(job["job_id"], provider_task_id)

    async def poll(self, job: dict) -> None:
        try:
            result = await self.provider.status(job["provider_task_id"])
            if result.status == "running":
                return
            if result.status == "failed":
                await self.store.fail_job(job["job_id"], result.error or "图片服务生成失败。")
                return
            data, _media_type = await self.provider.download_image(result.image_url)
            # A stable asset ID makes safe download/publication retries overwrite the
            # same file after a database outage rather than leave orphaned results.
            image_id = str(uuid5(NAMESPACE_URL, f"ruoyi-agent:image:{job['job_id']}"))
            relative_path = Path(str(job["thread_id"])) / f"{image_id}.png"
            width, height = await asyncio.to_thread(
                write_generated_image, data, self.settings.data_dir / relative_path,
            )
        except ImageInputError as exc:
            await self.store.fail_job(job["job_id"], self.error_text(exc))
            return
        except (ImageProviderError, httpx.HTTPError, OSError) as exc:
            # Poll/download/storage failures can recover on the next iteration.
            # Never repeat the original paid submission for a known provider ID.
            error = self.error_text(exc)
            logger.warning("Image task %s polling failed: %s", job["job_id"], error)
            await self.store.record_poll_error(job["job_id"], error)
            return
        await self.store.finish_job(job["job_id"], {
            "image_id": image_id, "user_id": job["user_id"], "thread_id": job["thread_id"],
            "name": "生成图片.png", "media_type": "image/png", "width": width, "height": height,
            "source": "generated", "path": relative_path.as_posix(), "job_id": job["job_id"],
        })

    async def run_once(self) -> bool:
        for job in await self.store.pending_jobs():
            await self.poll(job)
        job = await self.store.claim_job()
        if job is None:
            return False
        await self.submit(job)
        return True


async def main() -> None:
    from .config import load_image_settings
    from .provider import QwenImageProvider

    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    settings = load_image_settings()
    async with AsyncConnectionPool(
        os.environ["DATABASE_URL"], min_size=1, max_size=3,
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0}, timeout=10,
    ) as pool:
        await pool.wait()
        store = ImageStore(pool)
        await store.setup()
        await store.recover_submitting()
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds, trust_env=False, follow_redirects=False,
        ) as client:
            worker = ImageWorker(store, QwenImageProvider(settings, client), settings)
            READY_FILE.parent.mkdir(parents=True, exist_ok=True)
            READY_FILE.write_text(str(os.getpid()), encoding="ascii")
            try:
                while True:
                    if not await worker.run_once():
                        await asyncio.sleep(settings.poll_interval_seconds)
            finally:
                READY_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from ruoyi_agent.server import loop_factory

    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(main())
