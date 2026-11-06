"""External knowledge-management request contracts."""

from typing import Annotated
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class BaseFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=1000)] = ""


class BaseInfo(BaseModel):
    kb_id: str
    name: str
    description: str
    status: str
    error: str | None
    document_count: int = 0
    created_at: datetime


class BaseList(BaseModel):
    items: list[BaseInfo]
    total: int


class DocumentInfo(BaseModel):
    document_id: str
    kb_id: str
    name: str
    size: int
    media_type: str
    status: str
    stage: str
    error: str | None
    chunk_count: int
    created_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentInfo]
    total: int
