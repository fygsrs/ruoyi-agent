"""An agent tool for text-to-image and reference-image editing."""

import json
from typing import Annotated
from uuid import UUID

from langchain.tools import ToolRuntime, tool
from pydantic import Field

from ruoyi_agent.context import AgentContext
from .errors import ImageConflict, ImageInputError, ImageNotFound


@tool(response_format="content_and_artifact")
async def generate_image(
    prompt: Annotated[str, Field(min_length=1, max_length=12000)],
    runtime: ToolRuntime[AgentContext],
    reference_image_ids: Annotated[tuple[UUID, ...], Field(max_length=3)] = (),
    size: Annotated[str, Field(pattern=r"^\d{3,4}\*\d{3,4}$")] = "1024*1024",
):
    """生成图片或基于参考图修改图片。用户明确要求画图、生成海报/插画/配图时调用；修改上传的图片或此前生成的图片时，必须把真实image_id放入reference_image_ids（最多3张），不可省略参考图后重新凭空画。image_id从当前会话图片索引或本轮用户附图编号选择，不能编造；目标含糊时先请用户选图。prompt完整描述画面、风格、排版和需要准确显示的文字，编辑时写清要修改与保留的部分。size格式宽*高，如1024*1024、1536*1024、1024*1536，像素面积范围512²至2048²，比例不超过8:1。每次创建一个异步任务，返回job_id表示已提交，前端图片卡片会更新结果；提交后不要因尚未完成而重复调用，不要宣称生成已完成。"""
    context = runtime.context
    if context.user_id is None or context.images is None or context.thread_id is None:
        return json.dumps({"status": "failed", "message": "请登录后在聊天会话中生成图片。"}, ensure_ascii=False), None
    width, height = map(int, size.split("*"))
    if not 512 ** 2 <= width * height <= 2048 ** 2 or max(width, height) > min(width, height) * 8:
        return json.dumps({"status": "failed", "message": "图片尺寸超出模型支持范围，请调整宽高。"}, ensure_ascii=False), None
    try:
        job = await context.images.create_job(user_id=context.user_id, thread_id=context.thread_id, prompt=prompt,
                                              size=size, reference_image_ids=[str(item) for item in reference_image_ids],
                                              request_key=runtime.tool_call_id)
    except (ImageNotFound, ImageConflict, ImageInputError) as exc:
        return json.dumps({"status": "failed", "message": str(exc)}, ensure_ascii=False), None
    artifact = {"type": "image_generation", "job_id": job["job_id"]}
    return json.dumps({"status": job["status"], "job_id": job["job_id"],
                       "message": "图片任务已提交，请在图片卡片查看进度。"}, ensure_ascii=False), artifact
