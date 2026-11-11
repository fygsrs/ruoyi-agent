"""Trusted identity and dependencies for one agent invocation."""

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class AgentContext:
    # CLI invocations have no authenticated RuoYi user ID.
    user_id: int | None
    user_name: str
    greeting: bool = False
    permissions: frozenset[str] = frozenset()
    authorization: str = field(default="", repr=False, compare=False)
    java_client: httpx.AsyncClient | None = field(default=None, repr=False, compare=False)
    operations: Any = field(default=None, repr=False, compare=False)
    review: dict | None = field(default=None, repr=False, compare=False)
    analytics: Any = field(default=None, repr=False, compare=False)
    knowledge: Any = field(default=None, repr=False, compare=False)
    images: Any = field(default=None, repr=False, compare=False)
    thread_id: str | None = None
    image_index: tuple[dict, ...] = ()
    selected_images: tuple[dict, ...] = ()
