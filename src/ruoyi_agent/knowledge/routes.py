"""Shared reading and permission-controlled knowledge management."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from ruoyi_agent.auth import get_current_user
from ruoyi_agent.context import AgentContext
from ruoyi_agent.permissions import has_permission
from .schemas import BaseFields, BaseInfo, BaseList, DocumentInfo, DocumentList
from .service import KnowledgeService, UploadRejected
from .store import KnowledgeConflict, KnowledgeNotFound


router = APIRouter(prefix="/knowledge", tags=["knowledge"])
User = Annotated[AgentContext, Depends(get_current_user)]


def service(request: Request) -> KnowledgeService:
    return request.app.state.knowledge


def require(user: AgentContext, permission: str) -> None:
    if not has_permission(user, permission):
        raise HTTPException(403, "当前用户没有此操作权限。")


@router.get("/bases", response_model=BaseList)
async def list_bases(user: User, kb: Annotated[KnowledgeService, Depends(service)]):
    items = await kb.store.list_bases()
    return {"items": items, "total": len(items)}


@router.post("/bases", status_code=201, response_model=BaseInfo)
async def create_base(body: BaseFields, user: User, kb: Annotated[KnowledgeService, Depends(service)]):
    require(user, "knowledge:base:add")
    return await kb.store.create_base(str(uuid4()), body.name, body.description, user.user_id)


@router.patch("/bases/{kb_id}", response_model=BaseInfo)
async def update_base(kb_id: UUID, body: BaseFields, user: User, kb: Annotated[KnowledgeService, Depends(service)]):
    require(user, "knowledge:base:edit")
    return await kb.store.update_base(str(kb_id), body.name, body.description)


@router.delete("/bases/{kb_id}", status_code=202, response_model=BaseInfo)
async def delete_base(kb_id: UUID, user: User, kb: Annotated[KnowledgeService, Depends(service)]):
    require(user, "knowledge:base:remove")
    return await kb.store.request_delete_base(str(kb_id))


@router.get("/bases/{kb_id}/documents", response_model=DocumentList)
async def list_documents(kb_id: UUID, user: User, kb: Annotated[KnowledgeService, Depends(service)],
                         page: Annotated[int, Query(ge=1)] = 1,
                         page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    return await kb.store.list_documents(str(kb_id), page, page_size)


@router.post("/bases/{kb_id}/documents", status_code=202, response_model=DocumentInfo)
async def upload_document(kb_id: UUID, user: User, kb: Annotated[KnowledgeService, Depends(service)],
                          file: Annotated[UploadFile, File()]):
    require(user, "knowledge:document:upload")
    try:
        return await kb.upload(str(kb_id), file, user.user_id)
    except UploadRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()


@router.post("/documents/{document_id}/reprocess", status_code=202, response_model=DocumentInfo)
async def reprocess_document(document_id: UUID, user: User, kb: Annotated[KnowledgeService, Depends(service)]):
    require(user, "knowledge:document:reprocess")
    return await kb.store.reprocess_document(str(document_id))


@router.delete("/documents/{document_id}", status_code=202, response_model=DocumentInfo)
async def delete_document(document_id: UUID, user: User, kb: Annotated[KnowledgeService, Depends(service)]):
    require(user, "knowledge:document:remove")
    return await kb.store.request_delete_document(str(document_id))


@router.get("/documents/{document_id}/file")
async def document_file(document_id: UUID, user: User, kb: Annotated[KnowledgeService, Depends(service)]):
    document = await kb.store.get_document(str(document_id))
    path = kb.settings.data_dir / document["original_path"]
    if not path.is_file():
        raise HTTPException(404, "原文件已不存在。")
    return FileResponse(path, media_type=document["media_type"], filename=document["name"],
                        content_disposition_type="inline")


@router.get("/assets/{asset_id}")
async def asset_file(asset_id: UUID, user: User, kb: Annotated[KnowledgeService, Depends(service)]):
    asset = await kb.store.get_asset(str(asset_id))
    path = kb.settings.data_dir / asset["path"]
    if not path.is_file():
        raise HTTPException(404, "图片已不存在。")
    return FileResponse(path, media_type=asset["media_type"])


def register_errors(app):
    from fastapi.responses import JSONResponse

    @app.exception_handler(KnowledgeNotFound)
    async def not_found(_request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(KnowledgeConflict)
    async def conflict(_request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})
