"""Editable user review forms and validation of human decisions."""

from typing import Any, Literal

from langgraph.types import interrupt
from pydantic import ValidationError

from ruoyi_agent.ruoyi_client import RuoYiError, UserOptions
from ruoyi_agent.users.schemas import Operation, ReviewDecision, UpdateUserCommand, UserCommand


def empty_options() -> dict:
    return {"roles": [], "posts": [], "departments": []}


def review_payload(operation: Operation, fields: dict, options: dict, **extra: Any) -> dict:
    return {
        "kind": "user_review",
        "operation": operation,
        "title": {"create": "审核新增用户", "update": "审核修改用户", "delete": "确认删除用户"}[operation],
        "fields": fields,
        "options": options,
        **extra,
    }


def decision_result(operation: Operation, decision: ReviewDecision) -> dict | None:
    if decision.decision == "reject":
        return {"executed": False, "operation": operation, "status": "rejected", "message": "用户已拒绝本次操作。"}
    if decision.decision == "feedback":
        return {
            "executed": False,
            "operation": operation,
            "status": "needs_revision",
            "feedback": decision.feedback,
            "message": "用户提交了修改意见，请据此调整草稿并重新请求审核。",
        }
    return None


def validation_errors(exc: ValidationError) -> list[dict]:
    # Do not include rejected values: unexpected fields may contain credentials.
    return [{"field": ".".join(map(str, error["loc"])), "message": error["msg"]} for error in exc.errors(include_input=False)]


def enabled_departments(departments: list):
    for department in departments:
        if not department.disabled:
            yield department
            yield from enabled_departments(department.children)


def department_choices(departments: list) -> list[dict]:
    return [
        {"deptId": department.id, "deptName": department.label,
         "children": department_choices(department.children)}
        for department in departments if not department.disabled
    ]


def check_choices(command: UserCommand, options: UserOptions, before: dict | None) -> None:
    old = {} if before is None else before
    roles = {role.roleId for role in options.roles if role.status == "0"} | set(old.get("roleIds", []))
    posts = {post.postId for post in options.posts if post.status == "0"} | set(old.get("postIds", []))
    departments = {department.id for department in enabled_departments(options.departments)}
    if before is not None and before["deptId"] is not None:
        departments.add(before["deptId"])
    if not set(command.roleIds) <= roles or 1 in command.roleIds:
        raise RuoYiError("请选择当前用户可分配的有效角色，不能分配超级管理员角色。", code=422)
    if not set(command.postIds) <= posts:
        raise RuoYiError("请选择可用岗位。", code=422)
    if command.deptId is not None and command.deptId not in departments:
        raise RuoYiError("请选择当前用户可访问的有效部门。", code=422)


async def review_user_form(operation: Literal["create", "update"], fields: dict, options: UserOptions,
                           before: dict | None = None, errors: list[dict] | None = None):
    payload = review_payload(operation, fields, options.model_dump(), before=before)
    if errors:
        payload["errors"] = errors
    while True:
        decision = ReviewDecision.model_validate(interrupt(payload))
        result = decision_result(operation, decision)
        if result is not None:
            return result
        submitted = {**fields, **decision.fields}
        try:
            command = (UserCommand if operation == "create" else UpdateUserCommand).model_validate(submitted)
            if before is not None and (command.userId != before["userId"] or command.userName != before["userName"]):
                raise RuoYiError("修改用户时不能更换用户编号或登录账号，请重新发起操作。", code=422)
            check_choices(command, options, before)
            return command
        except ValidationError as exc:
            payload["errors"] = validation_errors(exc)
        except RuoYiError as exc:
            payload["errors"] = [{"field": "", "message": str(exc)}]
        # Keep only the supported form fields when redisplaying invalid input.
        fields = {key: value for key, value in submitted.items() if key in UpdateUserCommand.model_fields}
        payload["fields"] = fields
