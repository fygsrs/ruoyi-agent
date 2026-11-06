"""Parse documents with the official, model-free MinerU cloud SDK."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import mimetypes
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

from langchain_text_splitters import MarkdownHeaderTextSplitter
from mineru import MinerU
from pydantic import BaseModel, Field, TypeAdapter

if TYPE_CHECKING:
    from .config import KnowledgeSettings


SUPPORTED_EXTENSIONS = frozenset({
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp",
    ".txt", ".md",
})


@dataclass(frozen=True)
class ParsedAsset:
    asset_id: str
    path: Path
    media_type: str
    page: int | None


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    section: str | None
    page: int | None
    asset_ids: list[str]


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    blocks: list[ParsedBlock]
    assets: list[ParsedAsset]
    markdown_path: Path
    structure_path: Path


class _ContentBlock(BaseModel):
    """The cloud API's content-list V1 fields used for indexing."""

    type: str
    page_idx: int | None = Field(default=None, ge=0)
    text: str | None = None
    text_level: int | None = Field(default=None, ge=0)
    img_path: str | None = None
    image_caption: list[str] = Field(default_factory=list)
    image_footnote: list[str] = Field(default_factory=list)
    table_caption: list[str] = Field(default_factory=list)
    table_body: str | None = None
    table_footnote: list[str] = Field(default_factory=list)
    code_body: str | None = None
    code_caption: list[str] = Field(default_factory=list)
    list_items: list[str] = Field(default_factory=list)


_CONTENT_LIST = TypeAdapter(list[_ContentBlock])
_MARKDOWN_IMAGE = re.compile(r'(!\[[^\]]*\]\()([^\s)]+)([^)]*\))')
_HTML_IMAGE = re.compile(r'''(\bsrc\s*=\s*["'])([^"']+)(["'])''', re.IGNORECASE)


async def parse_document(source: Path, output_dir: Path, settings: KnowledgeSettings) -> ParsedDocument:
    """Write Markdown, content JSON and images into one document version directory.

    The caller retains the uploaded original in its document directory. SDK upload,
    polling, downloads and local writes run off the application's event loop.
    """
    return await asyncio.to_thread(_parse_document, source, output_dir, settings)


def _parse_document(source: Path, output_dir: Path, settings: KnowledgeSettings) -> ParsedDocument:
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"不支持的知识库文件格式：{suffix}")
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "markdown.md"
    structure_path = output_dir / "content_list.json"

    if suffix in {".txt", ".md"}:
        markdown = source.read_text(encoding="utf-8-sig")
        blocks = _markdown_blocks(markdown)
        structure = [
            {"type": "text", "text": block.text, "section": block.section, "page": None}
            for block in blocks
        ]
        assets = []
    else:
        if not settings.mineru_api_token:
            raise ValueError("请配置 MINERU_API_TOKEN 后解析 PDF、Office 或图片。")
        with MinerU(token=settings.mineru_api_token, base_url=settings.mineru_base_url) as client:
            result = client.extract(
                str(source), ocr=True, timeout=settings.mineru_timeout_seconds,
            )
        if result.state != "done":
            raise ValueError(f"MinerU 解析失败：{result.error}")
        if result.markdown is None or result.content_list is None:
            raise ValueError("MinerU 返回结果缺少 Markdown 或结构化内容列表。")

        items = _CONTENT_LIST.validate_python(result.content_list)
        # Preserve the provider's complete fields before normalizing asset paths.
        (output_dir / "mineru_content_list.json").write_text(
            json.dumps(result.content_list, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        path_map: dict[str, str] = {}
        asset_paths: dict[str, Path] = {}
        for image in result.images:
            asset_id = str(uuid5(NAMESPACE_URL, f"{output_dir.resolve().as_posix()}/images/{image.name}"))
            image_path = output_dir / "images" / f"{asset_id}{Path(image.name).suffix.lower()}"
            image_path.parent.mkdir(exist_ok=True)
            image_path.write_bytes(image.data)
            relative_path = image_path.relative_to(output_dir).as_posix()
            for reference in {image.path, f"images/{image.name}"}:
                if reference in path_map:
                    raise ValueError(f"MinerU 返回重复图片路径：{reference}")
                path_map[reference] = relative_path
            asset_paths[asset_id] = image_path

        markdown = _rewrite_images(result.markdown, path_map)
        structure = _normalize_paths(result.content_list, path_map)
        blocks = _content_blocks(items, path_map)
        asset_pages = {
            asset_id: block.page
            for block in reversed(blocks)
            for asset_id in block.asset_ids
        }
        assets = [
            ParsedAsset(
                asset_id=asset_id, path=path,
                media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                page=asset_pages.get(asset_id),
            )
            for asset_id, path in asset_paths.items()
        ]

    markdown_path.write_text(markdown, encoding="utf-8")
    structure_path.write_text(
        json.dumps(structure, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return ParsedDocument(markdown, blocks, assets, markdown_path, structure_path)


def _markdown_blocks(markdown: str) -> list[ParsedBlock]:
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#" * level, f"h{level}") for level in range(1, 7)],
        strip_headers=False,
    )
    return [
        ParsedBlock(
            text=document.page_content,
            section=" / ".join(document.metadata.values()) or None,
            page=None, asset_ids=[],
        )
        for document in splitter.split_text(markdown)
    ]


def _rewrite_images(text: str, paths: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return match[1] + paths.get(match[2], match[2]) + match[3]

    return _HTML_IMAGE.sub(replace, _MARKDOWN_IMAGE.sub(replace, text))


def _normalize_paths(value: Any, paths: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_paths(item, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_paths(item, paths) for item in value]
    if isinstance(value, str):
        return paths.get(value, _rewrite_images(value, paths))
    return value


def _content_blocks(items: list[_ContentBlock], paths: dict[str, str]) -> list[ParsedBlock]:
    blocks = []
    headings: dict[int, str] = {}
    for item in items:
        if item.text_level and item.text:
            headings = {level: title for level, title in headings.items() if level < item.text_level}
            headings[item.text_level] = item.text
        parts = []
        if item.text:
            parts.append(("#" * item.text_level + " " if item.text_level else "") + item.text)
        parts.extend(item.image_caption)
        parts.extend(item.table_caption)
        parts.extend(item.code_caption)
        if item.table_body:
            parts.append(item.table_body)
        if item.code_body:
            parts.append(f"```\n{item.code_body}\n```")
        parts.extend(item.list_items)
        if item.img_path:
            if item.img_path not in paths:
                raise ValueError(f"MinerU 图片资源缺失：{item.img_path}")
            parts.append(f"![]({item.img_path})")
        parts.extend(item.image_footnote)
        parts.extend(item.table_footnote)
        text = _rewrite_images("\n\n".join(parts), paths)
        asset_ids = list(dict.fromkeys(
            Path(match[2]).stem
            for pattern in (_MARKDOWN_IMAGE, _HTML_IMAGE)
            for match in pattern.finditer(text)
            if match[2] in paths.values()
        ))
        if text.strip():
            blocks.append(ParsedBlock(
                text=text, section=" / ".join(headings.values()) or None,
                page=item.page_idx + 1 if item.page_idx is not None else None,
                asset_ids=asset_ids,
            ))
    return blocks
