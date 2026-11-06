"""Uvicorn loop factory compatible with Psycopg async connections on Windows."""

import asyncio


def loop_factory():
    return asyncio.SelectorEventLoop()
