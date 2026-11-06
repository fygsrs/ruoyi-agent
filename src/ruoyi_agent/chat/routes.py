"""Authenticated HTTP endpoints for conversations and review options."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ruoyi_agent.auth import get_current_user
from ruoyi_agent.chat.schemas import ChatInput, GreetingRequest, ResumeRequest
from ruoyi_agent.chat.service import pending_review, stream_reply, thread_config, visible_messages
from ruoyi_agent.context import AgentContext
from ruoyi_agent.persistence import ConversationBusy
from ruoyi_agent.ruoyi_client import RuoYiClient, RuoYiError


router = APIRouter()


async def owned_thread(store, thread_id: UUID, user: AgentContext):
    if not await store.owns_thread(thread_id, user.user_id):
        raise HTTPException(404, "会话不存在。")


@router.get("/chat")
async def list_threads(request: Request, user: Annotated[AgentContext, Depends(get_current_user)]):
    return {"threads": await request.app.state.store.list_threads(user.user_id)}


@router.get("/chat/{thread_id}")
async def get_thread(thread_id: UUID, request: Request, user: Annotated[AgentContext, Depends(get_current_user)]):
    await owned_thread(request.app.state.store, thread_id, user)
    snapshot = await request.app.state.agent.aget_state(thread_config(thread_id))
    return {"thread_id": str(thread_id), "messages": visible_messages(snapshot),
            "review": pending_review(snapshot)}


@router.delete("/chat/{thread_id}", status_code=204)
async def delete_thread(thread_id: UUID, request: Request, user: Annotated[AgentContext, Depends(get_current_user)]):
    store = request.app.state.store
    await owned_thread(store, thread_id, user)
    try:
        async with store.lock(thread_id):
            await request.app.state.checkpointer.adelete_thread(str(thread_id))
            await store.delete_thread(thread_id, user.user_id)
    except ConversationBusy as exc:
        raise HTTPException(409, "当前会话正在处理中，请等待完成后再删除。") from exc
    return Response(status_code=204)


@router.post("/chat")
async def chat(body: ChatInput, request: Request, user: Annotated[AgentContext, Depends(get_current_user)]):
    thread_id = uuid4() if isinstance(body, GreetingRequest) else body.thread_id
    if isinstance(body, GreetingRequest):
        await request.app.state.store.create_thread(thread_id, user.user_id, "新对话")
    else:
        await owned_thread(request.app.state.store, thread_id, user)
    return StreamingResponse(stream_reply(request.app.state.agent, request.app.state.store, thread_id, user, body),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/chat/resume")
async def resume(body: ResumeRequest, request: Request, user: Annotated[AgentContext, Depends(get_current_user)]):
    await owned_thread(request.app.state.store, body.thread_id, user)
    return StreamingResponse(stream_reply(request.app.state.agent, request.app.state.store, body.thread_id, user, body),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/users/options")
async def user_options(user: Annotated[AgentContext, Depends(get_current_user)]):
    try:
        return (await RuoYiClient(user).user_options()).model_dump()
    except RuoYiError as exc:
        raise HTTPException(exc.code, str(exc)) from exc
