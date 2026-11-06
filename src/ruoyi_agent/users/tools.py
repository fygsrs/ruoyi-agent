"""User-management tools with editable, durable human review before writes."""

from typing import Annotated

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt
from pydantic import Field, ValidationError

from ruoyi_agent.context import AgentContext
from ruoyi_agent.permissions import require_permission
from ruoyi_agent.ruoyi_client import RuoYiClient, RuoYiError
from ruoyi_agent.users.review import (
    decision_result,
    department_choices,
    empty_options,
    review_payload,
    review_user_form,
    validation_errors,
)
from ruoyi_agent.users.schemas import Operation, ReviewDecision, TargetCommand, UserDraft, UsernameTarget


TOOL_PERMISSIONS = {
    "query_users": ("system:user:list",),
    "query_user_options": ("system:user:query", "system:user:list"),
    "create_user": ("system:user:add",),
    "update_user": ("system:user:edit",),
    "delete_user": ("system:user:remove",),
}


def failure(operation: Operation, error: RuoYiError) -> dict:
    return {
        "executed": False,
        "operation": operation,
        "status": "uncertain" if error.uncertain else "failed",
        "message": str(error),
    }


@tool
async def query_users(runtime: ToolRuntime[AgentContext],
                      user_name: Annotated[str, Field(min_length=1, max_length=30)] | None = None,
                      nick_name: Annotated[str, Field(min_length=1, max_length=30)] | None = None,
                      page: Annotated[int, Field(gt=0)] = 1) -> dict:
    """按登录账号 user_name 或昵称 nick_name 只读搜索当前用户有权查看的用户；至少提供一个搜索条件，每页20条。返回真实 userId、账号、昵称和部门供修改/删除工具使用，不要让人去查用户编号。若依支持模糊搜索：明确提供登录账号时只能使用账号完全一致的目标；昵称重名或含糊时向人展示账号、昵称、部门确认目标，不能自行挑选。has_more=true时可继续翻页。"""
    try:
        require_permission(runtime.context, "system:user:list")
        user_name = None if user_name is None else user_name.strip()
        nick_name = None if nick_name is None else nick_name.strip()
        if not user_name and not nick_name:
            raise RuoYiError("请提供要查找的登录账号或昵称。", code=422)
        result = await RuoYiClient(runtime.context).search_users(user_name=user_name, nick_name=nick_name, page=page)
        return {
            "users": [{"userId": user.userId, "userName": user.userName, "nickName": user.nickName,
                       "deptName": None if user.dept is None else user.dept.deptName, "status": user.status}
                      for user in result.rows],
            "total": result.total, "page": page, "has_more": page * 20 < result.total,
        }
    except RuoYiError as exc:
        return {"status": "failed", "message": str(exc)}


@tool
async def query_user_options(runtime: ToolRuntime[AgentContext]) -> dict:
    """只读查询当前用户可选的部门树、岗位和角色。用户按名称、简称或口语描述部门/岗位/角色时，必须先查询，再结合真实候选理解其意图，将编号填入新增或修改用户的草稿。部门树保留上下级以区分同名部门。有多个合理候选或找不到时不要随意选择，通过 selection_notes 提示人工在审核表单中选择。"""
    try:
        for permission in TOOL_PERMISSIONS["query_user_options"]:
            require_permission(runtime.context, permission)
        options = await RuoYiClient(runtime.context).user_options()
        return {
            "departments": department_choices(options.departments),
            "posts": [{"postId": post.postId, "postName": post.postName}
                      for post in options.posts if post.status == "0"],
            "roles": [{"roleId": role.roleId, "roleName": role.roleName}
                      for role in options.roles if role.status == "0"],
        }
    except RuoYiError as exc:
        return {"status": "failed", "message": str(exc)}


def operation_id(runtime: ToolRuntime[AgentContext]) -> str:
    return f"{runtime.config['configurable']['thread_id']}:{runtime.tool_call_id}"


async def execute_write(runtime: ToolRuntime[AgentContext], operation: Operation, payload: dict, callback) -> dict:
    context = runtime.context
    return await context.operations.execute(operation_id(runtime), context.user_id, operation, payload, callback)


async def existing_result(runtime: ToolRuntime[AgentContext]) -> dict | None:
    context = runtime.context
    return await context.operations.lookup(operation_id(runtime), context.user_id)


async def select_target(operation: Operation, user_id: int | None, client: RuoYiClient) -> int | dict:
    payload = review_payload(operation, {"userName": ""}, empty_options(), stage="select_target")
    if user_id is not None:
        try:
            return TargetCommand(userId=user_id).userId
        except ValidationError as exc:
            payload["errors"] = validation_errors(exc)
    while True:
        decision = ReviewDecision.model_validate(interrupt(payload))
        result = decision_result(operation, decision)
        if result is not None:
            return result
        try:
            target = UsernameTarget.model_validate(decision.fields)
            require_permission(client.context, "system:user:list")
            return await client.user_id_by_name(target.userName)
        except ValidationError as exc:
            payload["errors"] = validation_errors(exc)
        except RuoYiError as exc:
            if exc.code != 404:
                raise
            payload["fields"] = {"userName": target.userName}
            payload["errors"] = [{"field": "userName", "message": str(exc)}]


@tool
async def create_user(draft: UserDraft, runtime: ToolRuntime[AgentContext], selection_notes: list[str] | None = None) -> dict:
    """新增若依用户。部门、岗位或角色的名称/简称先通过 query_user_options 查询并理解候选，再填写对应 ID。含糊或不存在的选择留空，并用 selection_notes 说明需要人工确认的问题。资料不全也应传 draft={} 生成审核表单。批准后才执行。不要传密码，使用若依配置的初始密码。"""
    try:
        require_permission(runtime.context, "system:user:add")
        cached = await existing_result(runtime)
        if cached is not None:
            return cached
        if draft.userId is not None:
            raise RuoYiError("新增用户编号由若依生成，不能手动指定。", code=422)
        client = RuoYiClient(runtime.context)
        options = await client.user_options()
        fields = {
            "userName": "", "nickName": "", "deptId": None,
            "roleIds": [], "postIds": [], "phonenumber": "", "email": "",
            "sex": "2", "status": "0", "remark": "",
            **draft.model_dump(exclude_none=True),
        }
        errors = [{"field": "", "message": note} for note in (selection_notes or [])]
        reviewed = await review_user_form("create", fields, options, errors=errors)
        if isinstance(reviewed, dict):
            return reviewed
        body = reviewed.model_dump()

        async def write() -> dict:
            password = await client.initial_password()
            await client.request("POST", "/system/user", body={**body, "password": password})
            return {"executed": True, "operation": "create", "status": "succeeded", "target": {"userName": reviewed.userName}, "message": "用户新增成功，初始密码使用若依系统配置。"}

        return await execute_write(runtime, "create", body, write)
    except RuoYiError as exc:
        return failure("create", exc)


@tool
async def update_user(runtime: ToolRuntime[AgentContext], user_id: int | None = None, draft: UserDraft | None = None,
                      selection_notes: list[str] | None = None) -> dict:
    """修改若依用户。用户只需提供登录账号或昵称：先用 query_users 查询真实 user_id，多个可能目标时先请人确认账号。不要询问用户编号。未提供目标时可省略 user_id，让人在表单填写登录账号。部门、岗位或角色先通过 query_user_options 查询候选再填写 ID，不明确时保留原值，用 selection_notes 提示人工选择。仅传需要修改的资料，其余保留；资料不全也应传 draft={} 生成审核表单。批准后执行，不能修改登录账号或密码。"""
    try:
        require_permission(runtime.context, "system:user:edit")
        cached = await existing_result(runtime)
        if cached is not None:
            return cached
        client = RuoYiClient(runtime.context)
        target = await select_target("update", user_id, client)
        if isinstance(target, dict):
            return target
        if target == 1:
            raise RuoYiError("不能通过用户管理工具修改超级管理员。", code=403)
        details = await client.user_details(target)
        before = details.fields()
        options = await client.user_options(details)
        changes = {} if draft is None else draft.model_dump(exclude_none=True)
        errors = [{"field": "", "message": note} for note in (selection_notes or [])]
        fields = {**before, **changes}
        reviewed = await review_user_form("update", fields, options, before, errors)
        if isinstance(reviewed, dict):
            return reviewed
        original_review = runtime.context.review
        if (
            original_review is not None
            and original_review["operation"] == "update"
            and original_review["fields"].get("userId") == target
            and "before" in original_review
            and original_review["before"] != before
        ):
            return {
                "executed": False,
                "operation": "update",
                "status": "needs_revision",
                "message": "该用户资料在等待审核期间已被修改，本次修改未执行。请重新发起操作并审核最新资料。",
            }
        body = reviewed.model_dump()

        async def write() -> dict:
            await client.request("PUT", "/system/user", body=body)
            return {"executed": True, "operation": "update", "status": "succeeded", "target": {"userId": target, "userName": reviewed.userName}, "message": "用户资料修改成功。"}

        return await execute_write(runtime, "update", body, write)
    except RuoYiError as exc:
        return failure("update", exc)


@tool
async def delete_user(runtime: ToolRuntime[AgentContext], user_id: int | None = None) -> dict:
    """删除单个若依用户。用户提供登录账号或昵称时先用 query_users 查询真实 user_id，多个可能目标先请人确认账号，不要询问用户编号。未提供目标可省略 user_id，让人在表单填写登录账号。先展示准确身份供人工确认，批准后执行；不能删除当前登录用户或超级管理员。"""
    try:
        context = runtime.context
        require_permission(context, "system:user:remove")
        cached = await existing_result(runtime)
        if cached is not None:
            return cached
        client = RuoYiClient(context)
        target = await select_target("delete", user_id, client)
        if isinstance(target, dict):
            return target
        if target in (1, context.user_id):
            raise RuoYiError("不能删除超级管理员或当前登录用户。", code=403)
        details = await client.user_details(target)
        fields = details.fields()
        payload = review_payload("delete", fields, empty_options(), target={"userId": target, "userName": details.data.userName, "nickName": details.data.nickName})
        while True:
            decision = ReviewDecision.model_validate(interrupt(payload))
            result = decision_result("delete", decision)
            if result is not None:
                return result
            if decision.fields.get("userId", target) == target and set(decision.fields) <= set(fields):
                break
            payload["errors"] = [{"field": "userId", "message": "删除审核不能更换目标用户，请重新发起操作。"}]

        async def write() -> dict:
            await client.request("DELETE", f"/system/user/{target}")
            return {"executed": True, "operation": "delete", "status": "succeeded", "target": payload["target"], "message": "用户删除成功。"}

        return await execute_write(runtime, "delete", {"userId": target}, write)
    except RuoYiError as exc:
        return failure("delete", exc)


USER_TOOLS = [query_users, query_user_options, create_user, update_user, delete_user]
