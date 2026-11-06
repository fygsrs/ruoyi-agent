"""Shared RuoYi permission checks for tool selection and execution."""

from ruoyi_agent.context import AgentContext
from ruoyi_agent.ruoyi_client import RuoYiError


def has_permission(context: AgentContext, permission: str) -> bool:
    return "*:*:*" in context.permissions or permission in context.permissions


def require_permission(context: AgentContext, permission: str) -> None:
    if not has_permission(context, permission):
        raise RuoYiError(f"当前用户缺少权限：{permission}。", code=403)


def is_superadmin(context: AgentContext) -> bool:
    return context.user_id == 1


def require_admin(context: AgentContext) -> None:
    if not is_superadmin(context):
        raise RuoYiError("数据库分析工具仅允许若依超级管理员使用。", code=403)
