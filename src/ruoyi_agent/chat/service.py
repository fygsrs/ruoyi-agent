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
from ruoyi_agent.knowledge.citations import display_sources, turn_sources


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
    artifacts = []
    for message in snapshot.values.get("messages", []):
        if isinstance(message, HumanMessage):
            if artifacts:
                result.append({"role": "assistant", "content": "", "artifacts": artifacts})
                artifacts = []
            sources = []
            # The initial greeting prompt is an internal user turn.
            if message.additional_kwargs.get("greeting"):
                continue
            visible = {"role": "user", "content": message.additional_kwargs.get("display_content", message.text)}
            if message.additional_kwargs.get("images"):
                visible["images"] = message.additional_kwargs["images"]
            result.append(visible)
        elif isinstance(message, ToolMessage) and message.name == "search_knowledge" and message.artifact:
            sources = display_sources(message.artifact["sources"])
        elif isinstance(message, ToolMessage) and message.name == "generate_image" and message.artifact:
            artifacts = [*artifacts, message.artifact]
        elif isinstance(message, AIMessage) and (message.text or artifacts and not message.tool_calls):
            visible = {"role": "assistant", "content": message.text}
            if sources:
                visible["sources"] = sources
            if artifacts:
                visible["artifacts"] = artifacts
                artifacts = []
            result.append(visible)
    if artifacts:
        result.append({"role": "assistant", "content": "", "artifacts": artifacts})
    return result


def turn_image_artifacts(messages) -> list[dict]:
    artifacts = {}
    for message in messages:
        if isinstance(message, HumanMessage):
            artifacts.clear()
        elif isinstance(message, ToolMessage) and message.name == "generate_image" and message.artifact:
            artifacts[message.artifact["job_id"]] = message.artifact
    return list(artifacts.values())


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
                    content = body.content
                    image_data = {}
                    if user.selected_images:
                        content += "\n本轮参考图片编号（用于图片工具）：" + json.dumps(
                            [asset["image_id"] for asset in user.selected_images], ensure_ascii=False)
                        image_data = {"display_content": body.content, "images": list(user.selected_images)}
                    inputs = {"messages": [HumanMessage(content=content, additional_kwargs=image_data)]}
                    context = user
            if context.images is not None:
                context = replace(context, thread_id=str(thread_id),
                                  image_index=await context.images.context_assets(str(thread_id), context.user_id))
            yield encode_event("thread", {"thread_id": str(thread_id)})
            stream = agent.astream(inputs, config=config, context=context, stream_mode=["messages", "updates"])
            emitted_jobs = set()
            try:
                async for mode, value in stream:
                    if mode == "messages":
                        chunk, _metadata = value
                        if isinstance(chunk, AIMessageChunk) and chunk.text:
                            yield encode_event("delta", {"text": chunk.text})
                    elif mode == "updates" and "tools" in value:
                        for message in value["tools"].get("messages", []):
                            if isinstance(message, ToolMessage) and message.name == "generate_image" and message.artifact:
                                artifact = message.artifact
                                emitted_jobs.add(artifact["job_id"])
                                yield encode_event("artifact", artifact)
                snapshot = await agent.aget_state(config)
                for artifact in turn_image_artifacts(snapshot.values.get("messages", [])):
                    if artifact["job_id"] not in emitted_jobs:
                        yield encode_event("artifact", artifact)
                title = body.content[:40] if isinstance(body, ChatRequest) else None
                await store.touch(thread_id, title)
                review = pending_review(snapshot)
                sources = turn_sources(snapshot.values.get("messages", []))
                if sources:
                    yield encode_event("sources", {"items": display_sources(sources)})
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
