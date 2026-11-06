"""Conversation state, review resumption, and agent streaming."""

from dataclasses import replace
import json
from uuid import UUID

import anyio
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.types import Command
from openai import APIError

from ruoyi_agent.chat.schemas import ChatRequest, GreetingRequest, ResumeRequest
from ruoyi_agent.context import AgentContext
from ruoyi_agent.persistence import ConversationBusy
from ruoyi_agent.knowledge.citations import turn_sources


def encode_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def thread_config(thread_id: UUID) -> dict:
    return {"configurable": {"thread_id": str(thread_id)}, "recursion_limit": 30}


def pending_review(snapshot) -> dict | None:
    if not snapshot.interrupts:
        return None
    review = snapshot.interrupts[0]
    return {**review.value, "interrupt_id": review.id}


def visible_messages(snapshot) -> list[dict]:
    result = []
    sources = []
    for message in snapshot.values.get("messages", []):
        if isinstance(message, HumanMessage):
            sources = []
            # The initial greeting prompt is an internal user turn.
            if message.additional_kwargs.get("greeting"):
                continue
            result.append({"role": "user", "content": message.text})
        elif isinstance(message, ToolMessage) and message.name == "search_knowledge" and message.artifact:
            sources = message.artifact["sources"]
        elif isinstance(message, AIMessage) and message.text:
            visible = {"role": "assistant", "content": message.text}
            if sources:
                visible["sources"] = sources
            result.append(visible)
    return result


async def stream_reply(agent, store, thread_id: UUID, user: AgentContext, body):
    config = thread_config(thread_id)
    try:
        async with store.lock(thread_id):
            # A DELETE may finish after the HTTP route checked ownership but
            # before this streaming response acquires the conversation lock.
            if not await store.owns_thread(thread_id, user.user_id):
                yield encode_event("error", {"message": "会话不存在。"})
                return
            snapshot = await agent.aget_state(config)
            if isinstance(body, ResumeRequest):
                if body.interrupt_id not in {item.id for item in snapshot.interrupts}:
                    yield encode_event("error", {"message": "该审核已处理或已失效，请重新加载会话。"})
                    return
                if body.decision == "feedback" and not body.feedback.strip():
                    yield encode_event("error", {"message": "请填写反馈内容。"})
                    return
                resume = {"decision": body.decision,
                          "fields": body.fields.model_dump(exclude_unset=True),
                          "feedback": body.feedback}
                inputs = Command(resume={body.interrupt_id: resume})
                approved_review = next(item.value for item in snapshot.interrupts if item.id == body.interrupt_id)
                context = replace(user, review=approved_review)
            else:
                if snapshot.interrupts:
                    yield encode_event("error", {"message": "请先处理当前待审核操作。"})
                    return
                if snapshot.next:
                    # A disconnected or failed tool run is never replayed implicitly.
                    yield encode_event("error", {"message": "上一轮运行未正常完成，请新建会话；涉及用户变更时先到若依核查结果。"})
                    return
                if isinstance(body, GreetingRequest):
                    inputs = {"messages": [HumanMessage(content="请向我打个招呼。", additional_kwargs={"greeting": True})]}
                    context = replace(user, greeting=True)
                else:
                    messages = snapshot.values.get("messages", [])
                    if len(messages) >= 100 or sum(len(message.text) for message in messages) + len(body.content) > 64000:
                        yield encode_event("error", {"message": "会话已达到长度上限，请新建对话。"})
                        return
                    inputs = {"messages": [HumanMessage(content=body.content)]}
                    context = user
            yield encode_event("thread", {"thread_id": str(thread_id)})
            stream = agent.astream(inputs, config=config, context=context, stream_mode=["messages", "updates"])
            try:
                async for mode, value in stream:
                    if mode == "messages":
                        chunk, _metadata = value
                        if isinstance(chunk, AIMessageChunk) and chunk.text:
                            yield encode_event("delta", {"text": chunk.text})
                snapshot = await agent.aget_state(config)
                title = body.content[:40] if isinstance(body, ChatRequest) else None
                await store.touch(thread_id, title)
                review = pending_review(snapshot)
                sources = turn_sources(snapshot.values.get("messages", []))
                if sources:
                    yield encode_event("sources", {"items": sources})
                if review is not None:
                    yield encode_event("review_required", review)
                else:
                    yield encode_event("done", {})
            except APIError:
                yield encode_event("error", {"message": "模型服务暂时不可用，请稍后新建会话重试。"})
            finally:
                with anyio.CancelScope(shield=True):
                    await stream.aclose()
    except ConversationBusy:
        yield encode_event("error", {"message": "当前会话正在处理中，请等待完成后再操作。"})
