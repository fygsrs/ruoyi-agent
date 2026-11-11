"""Async DashScope adapter for Qwen image generation and editing."""

import asyncio
import base64
from dataclasses import dataclass
import mimetypes
from pathlib import Path
import re
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import ImageSettings
from .errors import ImageInputError, ImageProviderError, SubmissionUncertain


MAX_IMAGE_BYTES = 10 * 1024 * 1024
_RESULT_HOST = re.compile(
    r"(?:dashscope-result(?:-[a-z0-9-]+)?\.oss(?:-[a-z0-9-]+)?"
    r"|dashscope-[a-z0-9]+\.oss-accelerate)\.aliyuncs\.com"
)
_IMAGE_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp", "image/bmp", "image/tiff", "image/gif"}


@dataclass(frozen=True)
class ProviderResult:
    status: Literal["running", "succeeded", "failed"]
    image_url: str | None = None
    error: str | None = None


class _SubmittedTask(BaseModel):
    task_id: str = Field(min_length=1)


class _SubmissionResponse(BaseModel):
    output: _SubmittedTask


class _ImageContent(BaseModel):
    image: str | None = None


class _Message(BaseModel):
    content: list[_ImageContent]


class _Choice(BaseModel):
    message: _Message


class _TaskOutput(BaseModel):
    task_status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"]
    choices: list[_Choice] = Field(default_factory=list)
    code: str | None = None
    message: str | None = None


class _TaskResponse(BaseModel):
    output: _TaskOutput


class _ErrorResponse(BaseModel):
    code: str | None = None
    message: str | None = None


class QwenImageProvider:
    """Keep authentication on API calls; never forward it to result storage."""

    def __init__(self, settings: ImageSettings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def submit(self, prompt: str, size: str, references: list[Path]) -> str:
        content = []
        for path in references:
            try:
                data = await asyncio.to_thread(path.read_bytes)
            except OSError as exc:
                raise ImageInputError("参考图片文件无法读取，请重新上传。") from exc
            media_type = mimetypes.guess_type(path.name)[0]
            content.append({"image": f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"})
        content.append({"text": prompt})
        try:
            response = await self.client.post(
                f"{self.settings.base_url.rstrip('/')}/services/aigc/image-generation/generation",
                headers={**self._headers(), "X-DashScope-Async": "enable"},
                json={
                    "model": self.settings.model,
                    "input": {"messages": [{"role": "user", "content": content}]},
                    "parameters": {"size": size, "n": 1},
                },
                timeout=self.settings.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            raise SubmissionUncertain("图片任务提交时连接中断，供应商可能已接收，请勿自动重复提交。") from exc
        self._check_response(response, submitting=True)
        try:
            return _SubmissionResponse.model_validate_json(response.content).output.task_id
        except ValidationError as exc:
            raise SubmissionUncertain("图片服务未返回有效任务编号，无法确认是否已提交。") from exc

    async def status(self, task_id: str) -> ProviderResult:
        try:
            response = await self.client.get(
                f"{self.settings.base_url.rstrip('/')}/tasks/{quote(task_id, safe='')}",
                headers=self._headers(), timeout=self.settings.timeout_seconds, follow_redirects=False,
            )
        except httpx.TransportError as exc:
            raise ImageProviderError("暂时无法查询图片任务，请稍后重试。") from exc
        self._check_response(response)
        try:
            output = _TaskResponse.model_validate_json(response.content).output
        except ValidationError as exc:
            raise ImageProviderError("图片服务返回了无效的任务状态。") from exc
        if output.task_status in {"PENDING", "RUNNING"}:
            return ProviderResult("running")
        if output.task_status != "SUCCEEDED":
            return ProviderResult("failed", error=self._safe_error(output.code, output.message))
        for choice in output.choices:
            for content in choice.message.content:
                if content.image:
                    return ProviderResult("succeeded", image_url=content.image)
        raise ImageInputError("图片任务已完成，但供应商未返回图片。")

    async def download_image(self, url: str) -> tuple[bytes, str]:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ImageInputError("图片服务返回了无效的结果地址。") from exc
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or port not in {None, 443} or not _RESULT_HOST.fullmatch(parsed.hostname or "")):
            raise ImageInputError("图片服务返回了不支持的结果地址。")
        try:
            request = self.client.build_request("GET", url, timeout=self.settings.timeout_seconds)
            request.headers.pop("Authorization", None)
            request.headers.pop("Cookie", None)
            response = await self.client.send(request, auth=None, stream=True, follow_redirects=False)
            try:
                if response.status_code != 200:
                    error_type = (ImageInputError
                                  if 300 <= response.status_code < 500 and response.status_code not in {408, 429}
                                  else ImageProviderError)
                    raise error_type(f"图片下载失败（HTTP {response.status_code}）。")
                media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if media_type not in _IMAGE_MEDIA_TYPES:
                    raise ImageInputError("图片服务返回了不支持的图片格式。")
                chunks = []
                length = 0
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > MAX_IMAGE_BYTES:
                        raise ImageInputError("生成的图片超过 10MB，无法保存。")
                    chunks.append(chunk)
                return b"".join(chunks), media_type
            finally:
                await response.aclose()
        except httpx.TransportError as exc:
            raise ImageProviderError("图片下载连接中断，请稍后重试。") from exc

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.api_key}"}

    def _check_response(self, response: httpx.Response, *, submitting: bool = False) -> None:
        if response.is_success:
            return
        try:
            detail = _ErrorResponse.model_validate_json(response.content)
        except ValidationError:
            message = f"图片服务请求失败（HTTP {response.status_code}）。"
        else:
            message = f"图片服务请求失败（HTTP {response.status_code}）：{self._safe_error(detail.code, detail.message)}"
        if submitting and response.status_code >= 500:
            raise SubmissionUncertain(message + " 提交结果待确认，请勿自动重复提交。")
        raise ImageProviderError(message)

    def _safe_error(self, code: str | None, message: str | None) -> str:
        text = message or code or "图片生成任务失败。"
        if self.settings.api_key:
            text = text.replace(self.settings.api_key, "[已隐藏]")
        return re.sub(r"(?:https?://|data:)[^\s]+", "[已隐藏地址]", text)[:500]
