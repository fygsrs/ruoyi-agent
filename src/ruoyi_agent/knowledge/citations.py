"""Citation snapshots stored in tool messages and restored with conversations."""

from langchain_core.messages import HumanMessage, ToolMessage


def citation_key(source: dict) -> tuple:
    """Match the same passage in duplicate uploads without merging other origins."""
    return (source["kb_id"], source["document_name"], source["page"], source["section"],
            " ".join(source["excerpt"].split()))


def display_sources(sources: list[dict]) -> list[dict]:
    """Group duplicate historical passages while retaining every cited number."""
    grouped = {}
    for source in sources:
        key = citation_key(source)
        if key not in grouped:
            grouped[key] = source.copy()
        else:
            canonical = grouped[key]
            numbers = canonical.setdefault("source_ids", [canonical["source_id"]])
            if source["source_id"] not in numbers:
                numbers.append(source["source_id"])
    return list(grouped.values())


def turn_sources(messages) -> list[dict]:
    sources = {}
    for message in messages:
        if isinstance(message, HumanMessage):
            sources.clear()
        elif isinstance(message, ToolMessage) and message.name == "search_knowledge" and message.artifact:
            for source in message.artifact["sources"]:
                sources[source["chunk_id"]] = source
    return list(sources.values())
