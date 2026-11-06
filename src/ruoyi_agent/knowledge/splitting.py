"""Split parsed sections with LangChain while retaining citation metadata."""

from itertools import groupby

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .parser import ParsedDocument


def split_document(
    parsed: ParsedDocument,
    *,
    kb_id: str,
    document_id: str,
    version: int,
    document_name: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
) -> list[Document]:
    """Keep page and section boundaries and assign images to overlapping chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap, add_start_index=True,
        separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""],
    )
    chunks = []
    for (page, section), group in groupby(parsed.blocks, key=lambda block: (block.page, block.section)):
        blocks = list(group)
        text = "\n\n".join(block.text for block in blocks)
        spans = []
        offset = 0
        for block in blocks:
            spans.append((offset, offset + len(block.text), block.asset_ids))
            offset += len(block.text) + 2
        metadata = {
            "document_name": document_name, "kb_id": kb_id,
            "document_id": document_id, "version": version,
            "section": section, "page": page,
        }
        for chunk in splitter.create_documents([text], metadatas=[metadata]):
            start = chunk.metadata["start_index"]
            end = start + len(chunk.page_content)
            chunk.metadata["asset_ids"] = list(dict.fromkeys(
                asset_id
                for block_start, block_end, asset_ids in spans
                if block_start < end and block_end > start
                for asset_id in asset_ids
            ))
            chunks.append(chunk)
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = f"{document_id}:{version}:{index}"
    return chunks
