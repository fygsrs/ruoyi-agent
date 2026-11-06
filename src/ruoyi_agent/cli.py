"""Command-line entry point."""

import argparse
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="运行 RuoYi Agent。")
    parser.add_argument("prompt", help="发送给 Agent 的问题")
    args = parser.parse_args()

    from ruoyi_agent.agent import build_agent
    from ruoyi_agent.config import load_settings
    from ruoyi_agent.context import AgentContext

    agent = build_agent(load_settings())
    result = agent.invoke(
        {"messages": [{"role": "user", "content": args.prompt}]},
        context=AgentContext(user_id=None, user_name="本地命令行用户"),
    )
    print(result["messages"][-1].text)
