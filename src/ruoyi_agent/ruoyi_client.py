"""Access RuoYi through the current user's authenticated Java session."""

import json
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from ruoyi_agent.context import AgentContext


PositiveId = Annotated[StrictInt, Field(gt=0)]


class RuoYiError(Exception):
    def __init__(self, message: str, *, code: int = 502, uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


class JavaStatus(BaseModel):
    code: StrictInt
    msg: StrictStr = ""


class RoleOption(BaseModel):
    roleId: PositiveId
    roleName: StrictStr
    status: Literal["0", "1"]


class PostOption(BaseModel):
    postId: PositiveId
    postName: StrictStr
    status: Literal["0", "1"]


class DepartmentOption(BaseModel):
    id: PositiveId
    label: StrictStr
    disabled: bool = False
    children: list["DepartmentOption"] = Field(default_factory=list)


class UserOptions(BaseModel):
    roles: list[RoleOption]
    posts: list[PostOption]
    departments: list[DepartmentOption]


class JavaUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    userId: PositiveId
    userName: StrictStr
    nickName: StrictStr
    deptId: PositiveId | None = None
    phonenumber: StrictStr | None = None
    email: StrictStr | None = None
    sex: Literal["0", "1", "2"]
    status: Literal["0", "1"]
    remark: StrictStr | None = None


class JavaUserDetails(BaseModel):
    data: JavaUser
    roleIds: list[PositiveId]
    postIds: list[PositiveId]
    roles: list[RoleOption]
    posts: list[PostOption]

    def fields(self) -> dict[str, Any]:
        fields = self.data.model_dump()
        for key in ("phonenumber", "email", "remark"):
            if fields[key] is None:
                fields[key] = ""
        return {**fields, "roleIds": self.roleIds, "postIds": self.postIds}


class JavaChoices(BaseModel):
    roles: list[RoleOption]
    posts: list[PostOption]


class JavaDepartments(BaseModel):
    data: list[DepartmentOption]


class UserDepartment(BaseModel):
    deptName: StrictStr


class UserSummary(BaseModel):
    userId: PositiveId
    userName: StrictStr
    nickName: StrictStr
    status: Literal["0", "1"]
    dept: UserDepartment | None = None


class UserSearchPage(BaseModel):
    rows: list[UserSummary]
    total: Annotated[StrictInt, Field(ge=0)]


class JavaInitialPassword(BaseModel):
    msg: Annotated[StrictStr, Field(min_length=6, max_length=20, pattern=r'''^[^<>"'|\\]+$''')]


class RuoYiClient:
    def __init__(self, context: AgentContext):
        self.context = context

    async def request(self, method: str, path: str, *, body: dict | None = None,
                      params: dict[str, str | int] | None = None) -> dict:
        writing = method != "GET"
        try:
            response = await self.context.java_client.request(
                method,
                path,
                headers={"Authorization": self.context.authorization},
                json=body,
                params=params,
            )
        except httpx.TimeoutException as exc:
            message = "若依操作超时，结果尚未确认，请先检查用户列表。" if writing else "查询若依服务超时，请稍后重试。"
            raise RuoYiError(message, code=504, uncertain=writing) from exc
        except httpx.RequestError as exc:
            message = "若依连接中断，操作结果尚未确认，请先检查用户列表。" if writing else "无法连接若依服务，请稍后重试。"
            raise RuoYiError(message, uncertain=writing) from exc

        if response.status_code in (401, 403):
            raise RuoYiError("登录已失效或当前用户没有访问权限。", code=response.status_code)
        if response.status_code != 200:
            raise RuoYiError("若依服务返回异常，写入结果需要核实。" if writing else "若依服务返回异常。", uncertain=writing)
        try:
            payload = response.json()
            status = JavaStatus.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuoYiError("若依服务返回了无效数据。", uncertain=writing) from exc
        if status.code != 200:
            raise RuoYiError(status.msg or "若依拒绝了本次操作。", code=status.code)
        return payload

    async def search_users(self, *, user_name: str | None = None, nick_name: str | None = None,
                           page: int = 1) -> UserSearchPage:
        params = {"pageNum": page, "pageSize": 20}
        if user_name is not None:
            params["userName"] = user_name
        if nick_name is not None:
            params["nickName"] = nick_name
        payload = await self.request("GET", "/system/user/list", params=params)
        try:
            return UserSearchPage.model_validate(payload)
        except ValidationError as exc:
            raise RuoYiError("若依返回了无效用户列表。") from exc

    async def user_id_by_name(self, user_name: str) -> int:
        page = 1
        while True:
            result = await self.search_users(user_name=user_name, page=page)
            for user in result.rows:
                if user.userName == user_name:
                    return user.userId
            if page * 20 >= result.total:
                raise RuoYiError("未找到该登录账号，或当前用户无权查看，请核对账号。", code=404)
            page += 1

    async def user_details(self, user_id: int) -> JavaUserDetails:
        payload = await self.request("GET", f"/system/user/{user_id}")
        try:
            return JavaUserDetails.model_validate(payload)
        except ValidationError as exc:
            raise RuoYiError("用户不存在，或若依返回了无效用户资料。") from exc

    async def user_options(self, details: JavaUserDetails | None = None) -> UserOptions:
        if details is None:
            payload = await self.request("GET", "/system/user/")
            try:
                choices = JavaChoices.model_validate(payload)
            except ValidationError as exc:
                raise RuoYiError("若依返回了无效角色或岗位列表。") from exc
        else:
            choices = JavaChoices(roles=details.roles, posts=details.posts)
        payload = await self.request("GET", "/system/user/deptTree")
        try:
            departments = JavaDepartments.model_validate(payload)
        except ValidationError as exc:
            raise RuoYiError("若依返回了无效部门列表。") from exc
        return UserOptions(
            roles=[role for role in choices.roles if role.roleId != 1],
            posts=choices.posts,
            departments=departments.data,
        )

    async def initial_password(self) -> str:
        payload = await self.request("GET", "/system/config/configKey/sys.user.initPassword")
        try:
            return JavaInitialPassword.model_validate(payload).msg
        except ValidationError as exc:
            raise RuoYiError("若依初始密码配置不符合长度要求，请先修正系统配置。") from exc
