"""Tools available to the agent."""

from datetime import datetime

from langchain.tools import tool


@tool
def get_current_time() -> str:
    """查询当前本地日期、时间和时区偏移。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")
