"""Validated request models for chat turns and tool reviews."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


MessageText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=8000)]
ReviewId = Annotated[int, Field(strict=True, gt=0)]
ReviewIds = Annotated[list[ReviewId], Field(max_length=100)]


class GreetingRequest(BaseModel):
    action: Literal["greet"]


class ChatRequest(BaseModel):
    action: Literal["chat"]
    thread_id: UUID
    content: MessageText


ChatInput = Annotated[GreetingRequest | ChatRequest, Field(discriminator="action")]


class ReviewFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    userId: ReviewId | None = None
    userName: Annotated[str, Field(max_length=30)] | None = None
    nickName: Annotated[str, Field(max_length=30)] | None = None
    deptId: ReviewId | None = None
    roleIds: ReviewIds | None = None
    postIds: ReviewIds | None = None
    phonenumber: Annotated[str, Field(max_length=11)] | None = None
    email: Annotated[str, Field(max_length=50)] | None = None
    sex: Annotated[str, Field(max_length=1)] | None = None
    status: Annotated[str, Field(max_length=1)] | None = None
    remark: Annotated[str, Field(max_length=500)] | None = None


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: UUID
    interrupt_id: Annotated[str, Field(min_length=1, max_length=128)]
    decision: Literal["approve", "reject", "feedback"]
    fields: ReviewFields = Field(default_factory=ReviewFields)
    feedback: Annotated[str, Field(max_length=2000)] = ""
