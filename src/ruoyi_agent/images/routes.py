"""Authenticated image uploads, job status and private image downloads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from ruoyi_agent.auth import get_current_user
from ruoyi_agent.chat.routes import owned_thread
from ruoyi_agent.context import AgentContext
from ruoyi_agent.persistence import ConversationBusy
from .errors import ImageConflict, ImageInputError, ImageNotFound


router = APIRouter(tags=["images"])
User = Annotated[AgentContext, Depends(get_current_user)]


@router.post("/chat/{thread_id}/images", status_code=201)
async def upload_image(thread_id: UUID, request: Request, user: User, file: Annotated[UploadFile, File()]):
    store = request.app.state.store
    try:
        async with store.lock(thread_id):
            await owned_thread(store, thread_id, user)
            return await user.images.upload(str(thread_id), user.user_id, file)
    except ConversationBusy as exc:
        raise HTTPException(409, "会话正在处理中，请稍后上传参考图。") from exc
    finally:
        await file.close()


@router.get("/image-jobs/{job_id}")
async def image_job(job_id: UUID, user: User):
    return await user.images.job(str(job_id), user.user_id)


@router.get("/images/{image_id}")
async def image_file(image_id: UUID, user: User):
    asset = await user.images.store.get_asset(str(image_id), user.user_id)
    path = user.images.settings.data_dir / asset["path"]
    if not path.is_file():
        raise HTTPException(404, "图片文件已不存在。")
    return FileResponse(path, media_type=asset["media_type"], filename=asset["name"],
                        content_disposition_type="inline")


def register_errors(app):
    @app.exception_handler(ImageNotFound)
    async def not_found(_request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ImageConflict)
    async def conflict(_request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ImageInputError)
    async def invalid_input(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})
