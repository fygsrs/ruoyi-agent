"""Citation snapshots stored in tool messages and restored with conversations."""

from langchain_core.messages import HumanMessage, ToolMessage


def turn_sources(messages) -> list[dict]:
    sources = {}
    for message in messages:
        if isinstance(message, HumanMessage):
            sources.clear()
        elif isinstance(message, ToolMessage) and message.name == "search_knowledge" and message.artifact:
            for source in message.artifact["sources"]:
                sources[source["chunk_id"]] = source
    return list(sources.values())
