"""Validate RuoYi bearer tokens through the existing Java service."""

import json
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from ruoyi_agent.context import AgentContext


class RuoYiStatus(BaseModel):
    code: StrictInt


class RuoYiUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    userId: Annotated[StrictInt, Field(gt=0)]
    userName: Annotated[StrictStr, Field(min_length=1, max_length=64)]


class RuoYiInfo(BaseModel):
    user: RuoYiUser
    permissions: list[StrictStr]


bearer = HTTPBearer(auto_error=False)


def auth_error(status_code: int, message: str) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return HTTPException(status_code=status_code, detail=message, headers=headers)


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AgentContext:
    if credentials is None:
        raise auth_error(401, "请先登录若依系统。")

    java_client: httpx.AsyncClient = request.app.state.java_client
    try:
        response = await java_client.get(
            "/getInfo",
            headers={"Authorization": f"Bearer {credentials.credentials}"},
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "若依身份验证超时，请稍后重试。") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "无法连接若依服务，请稍后重试。") from exc

    if response.status_code == 401:
        raise auth_error(401, "登录已失效，请重新登录。")
    if response.status_code == 403:
        raise auth_error(403, "当前用户没有访问权限。")
    if response.status_code != 200:
        raise HTTPException(502, "若依身份验证服务返回异常。")

    try:
        payload = response.json()
        status = RuoYiStatus.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(502, "若依身份验证服务返回了无效数据。") from exc

    if status.code == 401:
        raise auth_error(401, "登录已失效，请重新登录。")
    if status.code == 403:
        raise auth_error(403, "当前用户没有访问权限。")
    if status.code != 200:
        raise HTTPException(502, "若依身份验证服务返回异常。")

    try:
        info = RuoYiInfo.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(502, "若依身份验证服务返回了无效用户信息。") from exc

    return AgentContext(
        user_id=info.user.userId,
        user_name=info.user.userName,
        permissions=frozenset(info.permissions),
        authorization=f"Bearer {credentials.credentials}",
        java_client=java_client,
        operations=request.app.state.store,
        analytics=request.app.state.analytics,
        knowledge=request.app.state.knowledge,
        images=request.app.state.images,
    )
