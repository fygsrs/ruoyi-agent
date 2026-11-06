"""Validated drafts, commands, and human review decisions for user management."""

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ruoyi_agent.ruoyi_client import PositiveId


Operation = Literal["create", "update", "delete"]


class UserDraft(BaseModel):
    """A partial user form; missing fields are completed during human review."""

    model_config = ConfigDict(extra="forbid", strict=True)

    userId: int | None = None
    userName: str | None = None
    nickName: str | None = None
    deptId: Annotated[int, Field(description="先查询 query_user_options，从真实候选中按用户意图选择部门编号；不明确时留空供人工选择。")] | None = None
    roleIds: list[int] | None = None
    postIds: Annotated[list[int], Field(description="先查询 query_user_options，从真实候选中按用户意图选择岗位编号；不明确时不要猜测。")] | None = None
    phonenumber: str | None = None
    email: str | None = None
    sex: str | None = None
    status: str | None = None
    remark: str | None = None


class UserCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    userName: Annotated[str, Field(min_length=2, max_length=20)]
    nickName: Annotated[str, Field(min_length=1, max_length=30)]
    deptId: PositiveId | None = None
    roleIds: list[PositiveId] = Field(default_factory=list)
    postIds: list[PositiveId] = Field(default_factory=list)
    phonenumber: Annotated[str, Field(max_length=11)] = ""
    email: Annotated[str, Field(max_length=50)] = ""
    sex: Literal["0", "1", "2"] = "2"
    status: Literal["0", "1"] = "0"
    remark: Annotated[str, Field(max_length=500)] = ""

    @field_validator("phonenumber")
    @classmethod
    def valid_phone(cls, value: str) -> str:
        if value and re.fullmatch(r"1[3-9]\d{9}", value) is None:
            raise ValueError("请输入有效的 11 位手机号码")
        return value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if value and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) is None:
            raise ValueError("请输入有效邮箱")
        return value


class UpdateUserCommand(UserCommand):
    userId: PositiveId
    userName: Annotated[str, Field(min_length=1, max_length=30)]


class TargetCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    userId: PositiveId


class UsernameTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    userName: Annotated[str, Field(min_length=1, max_length=30)]


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["approve", "reject", "feedback"]
    fields: dict[str, Any] = Field(default_factory=dict)
    feedback: Annotated[str, Field(max_length=2000)] = ""
