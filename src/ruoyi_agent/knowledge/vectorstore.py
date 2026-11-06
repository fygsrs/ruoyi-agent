"""LangChain Milvus storage with embedding and reranking inside Milvus."""

from __future__ import annotations

import asyncio
import json
from threading import Lock

from langchain_core.documents import Document
from langchain_milvus import BM25BuiltInFunction, Milvus, TextEmbeddingBuiltInFunction
from pymilvus import Function, FunctionType

from ruoyi_agent.knowledge.config import KnowledgeSettings


COLLECTION_NAME = "ruoyi_knowledge_chunks"
EMBEDDING_DIMENSION = 1024
MILVUS_TIMEOUT = 60


class KnowledgeVectorStore:
    """Store chunks in one application-owned collection.

    Document metadata contains ``chunk_id``, ``kb_id``, ``document_id``,
    ``version``, ``document_name``, ``section``, ``page`` and ``asset_ids``.
    The caller supplies the IDs of ready, authorized documents on every search.
    No connection or model request is made until an operation needs Milvus.
    """

    def __init__(self, settings: KnowledgeSettings) -> None:
        self._settings = settings
        self._store: Milvus | None = None
        self._initialization_lock = Lock()

    def _get_store(self) -> Milvus:
        with self._initialization_lock:
            if self._store is None:
                settings = self._settings
                if not settings.milvus_uri or not settings.milvus_token:
                    raise ValueError("请配置 MILVUS_URI 和 MILVUS_TOKEN。")
                self._store = Milvus(
                    embedding_function=None,
                    collection_name=COLLECTION_NAME,
                    connection_args={
                        "uri": settings.milvus_uri,
                        "token": settings.milvus_token,
                        "timeout": MILVUS_TIMEOUT,
                    },
                    consistency_level="Strong",
                    timeout=MILVUS_TIMEOUT,
                    drop_old=False,
                    auto_id=False,
                    primary_field="chunk_id",
                    text_field="text",
                    vector_field=["dense", "sparse"],
                    enable_dynamic_field=True,
                    builtin_function=[
                        TextEmbeddingBuiltInFunction(
                            input_field_names="text",
                            output_field_names="dense",
                            dim=EMBEDDING_DIMENSION,
                            function_name="ruoyi_knowledge_embedding",
                            params={
                                "provider": "dashscope",
                                "model_name": settings.milvus_embedding_model,
                                "dim": str(EMBEDDING_DIMENSION),
                            },
                        ),
                        BM25BuiltInFunction(
                            input_field_names="text",
                            output_field_names="sparse",
                            analyzer_params={"type": "chinese"},
                            function_name="ruoyi_knowledge_bm25",
                        ),
                    ],
                    index_params=[
                        {"index_type": "AUTOINDEX", "metric_type": "COSINE"},
                        {
                            "index_type": "SPARSE_INVERTED_INDEX",
                            "metric_type": "BM25",
                        },
                    ],
                    search_params=[
                        {"metric_type": "COSINE", "params": {}},
                        {"metric_type": "BM25", "params": {}},
                    ],
                )
            return self._store

    async def add_documents(self, documents: list[Document]) -> list[str]:
        if not documents:
            return []
        return await asyncio.to_thread(self._add_documents, documents)

    def _add_documents(self, documents: list[Document]) -> list[str]:
        store = self._get_store()
        if store.col is None:
            # In pinned langchain-milvus 0.4.0, first-insert initialization leaks
            # self.timeout into insert kwargs and passes timeout twice. Initialize
            # the server-function schema before entering add_embeddings instead.
            store._init(embeddings=[])
        return store.add_documents(
            documents, ids=[document.metadata["chunk_id"] for document in documents],
        )

    async def delete_document(
        self, document_id: str, version: int | None = None
    ) -> None:
        """Delete all chunks, or only the chunks from a failed document version."""
        await asyncio.to_thread(self._delete_document, document_id, version)

    def _delete_document(self, document_id: str, version: int | None) -> None:
        store = self._get_store()
        if store.col is None:
            return
        expression = f"document_id == {json.dumps(document_id, ensure_ascii=False)}"
        if version is not None:
            expression += f" and version == {version}"
        if not store.delete(expr=expression, timeout=MILVUS_TIMEOUT):
            raise RuntimeError("删除知识库文档向量失败。")

    async def search(
        self,
        query: str,
        kb_ids: list[str] | None,
        document_ids: list[str],
        limit: int = 6,
    ) -> list[Document]:
        # An empty authorization scope must never become an unfiltered search.
        if not document_ids or kb_ids == []:
            return []
        return await asyncio.to_thread(
            self._search, query, kb_ids, document_ids, limit
        )

    def _search(
        self,
        query: str,
        kb_ids: list[str] | None,
        document_ids: list[str],
        limit: int,
    ) -> list[Document]:
        expression = f"document_id in {json.dumps(document_ids, ensure_ascii=False)}"
        if kb_ids is not None:
            expression += f" and kb_id in {json.dumps(kb_ids, ensure_ascii=False)}"
        ranker = Function(
            name="ruoyi_knowledge_rerank",
            input_field_names=["text"],
            function_type=FunctionType.RERANK,
            params={
                "reranker": "model",
                "provider": "ali",
                "model_name": self._settings.milvus_rerank_model,
                "queries": [query],
            },
        )
        matches = self._get_store().similarity_search_with_score(
            query,
            k=limit,
            fetch_k=max(20, limit * 4),
            expr=expression,
            reranker=ranker,
        )
        for document, score in matches:
            document.metadata["score"] = float(score)
        return [document for document, _ in matches]

    async def close(self) -> None:
        if self._store is not None:
            await asyncio.to_thread(self._store.client.close)
