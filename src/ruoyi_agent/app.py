"""FastAPI application creation and shared resource lifecycle."""

from contextlib import AsyncExitStack, asynccontextmanager
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ruoyi_agent.agent import build_agent
from ruoyi_agent.analytics.executor import AnalyticsExecutor
from ruoyi_agent.chat.routes import router as chat_router
from ruoyi_agent.config import load_settings
from ruoyi_agent.persistence import PostgresStore
from ruoyi_agent.knowledge.config import load_knowledge_settings
from ruoyi_agent.knowledge.routes import router as knowledge_router, register_errors
from ruoyi_agent.knowledge.service import KnowledgeService
from ruoyi_agent.knowledge.store import KnowledgeStore
from ruoyi_agent.knowledge.vectorstore import KnowledgeVectorStore


def create_app(*, agent: Any = None, java_client: httpx.AsyncClient | None = None, store=None,
               analytics=None, checkpointer=None, knowledge=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        async with AsyncExitStack() as stack:
            if store is None:
                database_url = os.environ["DATABASE_URL"]
                pool = AsyncConnectionPool(database_url, min_size=1, max_size=12, open=False,
                                           check=AsyncConnectionPool.check_connection,
                                           kwargs={"autocommit": True, "row_factory": dict_row,
                                                   "prepare_threshold": 0}, timeout=10)
                await stack.enter_async_context(pool)
                await pool.wait()
                application.state.store = PostgresStore(pool)
                await application.state.store.setup()
                saver = AsyncPostgresSaver(pool)
                await saver.setup()
                knowledge_store = KnowledgeStore(pool)
                await knowledge_store.setup()
                knowledge_settings = load_knowledge_settings()
                vectors = KnowledgeVectorStore(knowledge_settings)
                stack.push_async_callback(vectors.close)
                application.state.knowledge = KnowledgeService(knowledge_store, vectors, knowledge_settings)
            else:
                application.state.store = store
                application.state.knowledge = knowledge
                saver = checkpointer
            application.state.checkpointer = saver
            application.state.agent = build_agent(load_settings(), checkpointer=saver) if agent is None else agent
            application.state.java_client = java_client or await stack.enter_async_context(httpx.AsyncClient(
                base_url=os.environ.get("RUOYI_BASE_URL", "http://127.0.0.1:8080"),
                timeout=httpx.Timeout(10.0), follow_redirects=False, trust_env=False))
            executor = analytics
            if executor is None and agent is None:
                executor = await AnalyticsExecutor.create(
                    host=os.environ['ANALYTICS_MYSQL_HOST'], port=int(os.environ['ANALYTICS_MYSQL_PORT']),
                    user=os.environ['ANALYTICS_MYSQL_USER'], password=os.environ['ANALYTICS_MYSQL_PASSWORD'],
                    databases=os.environ['ANALYTICS_MYSQL_DATABASES'].split(','))
                stack.push_async_callback(executor.close)
            application.state.analytics = executor
            yield

    application = FastAPI(title="RuoYi Agent", lifespan=lifespan)

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    application.include_router(chat_router)
    application.include_router(knowledge_router)
    register_errors(application)
    return application
