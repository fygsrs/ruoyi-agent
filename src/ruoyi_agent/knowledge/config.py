"""Knowledge ingestion and retrieval configuration."""

from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass(frozen=True)
class KnowledgeSettings:
    mineru_api_token: str = field(repr=False)
    milvus_uri: str
    milvus_token: str = field(repr=False)
    mineru_base_url: str = "https://mineru.net/api/v4"
    mineru_timeout_seconds: int = 600
    milvus_embedding_model: str = "qwen3.7-text-embedding-flash"
    milvus_rerank_model: str = "qwen3.7-text-rerank"
    data_dir: Path = Path(__file__).resolve().parents[3] / "data" / "knowledge"
    max_upload_bytes: int = 50 * 1024 * 1024
    chunk_size: int = 1000
    chunk_overlap: int = 150


def load_knowledge_settings() -> KnowledgeSettings:
    return KnowledgeSettings(
        mineru_api_token=os.environ["MINERU_API_TOKEN"],
        milvus_uri=os.environ["MILVUS_URI"],
        milvus_token=os.environ["MILVUS_TOKEN"],
        mineru_base_url=os.environ.get("MINERU_BASE_URL", "https://mineru.net/api/v4"),
        milvus_embedding_model=os.environ.get("MILVUS_EMBEDDING_MODEL", "qwen3.7-text-embedding-flash"),
        milvus_rerank_model=os.environ.get("MILVUS_RERANK_MODEL", "qwen3.7-text-rerank"),
        data_dir=Path(os.environ.get("KNOWLEDGE_DATA_DIR", str(KnowledgeSettings.data_dir))).resolve(),
    )
