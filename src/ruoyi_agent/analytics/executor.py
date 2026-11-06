"""Bounded MySQL reads through a separate, read-only connection pool."""

import asyncio
from base64 import b64encode
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from time import monotonic

import aiomysql

from ruoyi_agent.analytics.sql_policy import AnalyticsError, _prepare_sql


def _validate_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 64 or "\0" in value:
        raise AnalyticsError(f"{label}必须是 1 至 64 个字符且不含空字符。")


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, bytes):
        return "base64:" + b64encode(value).decode("ascii")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported MySQL result type: {type(value).__name__}")


def _json_bytes(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


class _ResultBuffer:
    """Limit rows and UTF-8 JSON bytes of the columns/rows result data."""

    def __init__(self, columns: list[str], max_rows: int, max_bytes: int):
        self.columns = columns
        self.rows: list[list] = []
        self.truncated = False
        self._max_rows = max_rows
        self._max_bytes = max_bytes
        self._size = _json_bytes({"columns": columns, "rows": []})
        if self._size > max_bytes:
            raise AnalyticsError("查询列信息超过结果字节限制，请减少选择的列。")

    def append(self, row: tuple) -> bool:
        if len(self.rows) == self._max_rows:
            self.truncated = True
            return False
        values = [_json_value(value) for value in row]
        size = _json_bytes(values) + (1 if self.rows else 0)
        if self._size + size > self._max_bytes:
            self.truncated = True
            return False
        self.rows.append(values)
        self._size += size
        return True


class AnalyticsExecutor:
    """Read live metadata and bounded results from configured business schemas."""

    def __init__(self, pool, databases, query_timeout_ms, max_rows, max_bytes):
        self._pool = pool
        self._databases = frozenset(databases)
        self._query_timeout_ms = query_timeout_ms
        self._max_rows = max_rows
        self._max_bytes = max_bytes

    @classmethod
    async def create(
        cls, *, host: str, port: int, user: str, password: str,
        databases: list[str], query_timeout_ms: int = 5000,
        max_rows: int = 200, max_bytes: int = 65536, max_connections: int = 2,
    ):
        if not host or not user:
            raise AnalyticsError("必须配置独立的 MySQL 分析主机和只读账号。")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise AnalyticsError("MySQL 端口必须在 1 至 65535 之间。")
        for name, value in (
            ("query_timeout_ms", query_timeout_ms), ("max_rows", max_rows),
            ("max_bytes", max_bytes), ("max_connections", max_connections),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise AnalyticsError(f"{name} 必须是正整数。")
        if not isinstance(databases, list) or not databases:
            raise AnalyticsError("必须显式配置至少一个业务数据库。")
        for database in databases:
            _validate_identifier(database, "数据库名")
        if len(set(databases)) != len(databases):
            raise AnalyticsError("业务数据库配置不能重复。")

        try:
            async with asyncio.timeout(query_timeout_ms / 1000):
                pool = await aiomysql.create_pool(
                    host=host, port=port, user=user, password=password,
                    minsize=1, maxsize=max_connections, autocommit=True,
                    charset="utf8mb4", local_infile=False,
                    connect_timeout=query_timeout_ms / 1000,
                    # aiomysql 0.3.2 interpolates this option directly into
                    # SET sql_mode=<value>, so it requires an SQL literal.
                    sql_mode="'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'",
                    init_command=(
                        f"SET SESSION max_execution_time = {query_timeout_ms}, "
                        "transaction_read_only = 1"
                    ),
                )
        except (aiomysql.Error, TimeoutError) as error:
            raise AnalyticsError("MySQL 分析连接初始化失败，请检查只读账号、网络和服务端超时设置。") from error

        executor = cls(pool, databases, query_timeout_ms, max_rows, max_bytes)
        ready = False
        try:
            available = await executor.databases()
            if set(available) != set(databases):
                raise AnalyticsError("部分已配置业务数据库不存在或只读账号无权访问。")
            ready = True
            return executor
        finally:
            if not ready:
                await executor.close()

    async def close(self) -> None:
        self._pool.close()
        await self._pool.wait_closed()

    def _check_database(self, database: str) -> None:
        if database not in self._databases:
            raise AnalyticsError("请选择已配置的业务数据库。")

    @asynccontextmanager
    async def _connection(self):
        try:
            # This also bounds pool queueing and result transfer. Each server
            # connection separately has max_execution_time and READ ONLY set.
            async with asyncio.timeout(self._query_timeout_ms / 1000):
                async with self._pool.acquire() as connection:
                    completed = False
                    try:
                        yield connection
                        completed = True
                    finally:
                        # Do not return an interrupted protocol stream to the
                        # pool; closing it also aborts pending network results.
                        if not completed:
                            connection.close()
        except TimeoutError as error:
            raise AnalyticsError(f"分析请求超过 {self._query_timeout_ms} 毫秒时限。") from error
        except aiomysql.Error as error:
            raise AnalyticsError(f"MySQL 分析请求失败（错误码 {error.args[0]}）：{error.args[1]}") from error

    async def databases(self) -> list[str]:
        names = sorted(self._databases)
        placeholders = ",".join("%s" for _ in names)
        async with self._connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                    f"WHERE SCHEMA_NAME IN ({placeholders}) ORDER BY SCHEMA_NAME",
                    names,
                )
                return [row[0] for row in await cursor.fetchall()]

    async def tables(self, database: str) -> list[dict]:
        self._check_database(database)
        async with self._connection() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT TABLE_NAME AS name, TABLE_COMMENT AS comment, TABLE_TYPE AS type "
                    "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
                    (database,),
                )
                return list(await cursor.fetchall())

    async def table_schemas(self, database: str, table_names: list[str]) -> list[dict]:
        self._check_database(database)
        if not isinstance(table_names, list) or not table_names:
            raise AnalyticsError("请提供至少一个表名。")
        for name in table_names:
            _validate_identifier(name, "表名")
        if len(set(table_names)) != len(table_names):
            raise AnalyticsError("表名不能重复。")
        placeholders = ",".join("%s" for _ in table_names)
        parameters = (database, *table_names)
        async with self._connection() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT TABLE_NAME AS name, TABLE_COMMENT AS comment "
                    "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s "
                    f"AND TABLE_NAME IN ({placeholders})",
                    parameters,
                )
                schemas = {
                    row["name"]: {**row, "columns": [], "foreign_keys": []}
                    for row in await cursor.fetchall()
                }
                if set(schemas) != set(table_names):
                    raise AnalyticsError("部分请求的表不存在或只读账号无权访问。")
                await cursor.execute(
                    "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS name, COLUMN_TYPE AS data_type, "
                    "IS_NULLABLE AS nullable, COLUMN_COMMENT AS comment "
                    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s "
                    f"AND TABLE_NAME IN ({placeholders}) ORDER BY TABLE_NAME, ORDINAL_POSITION",
                    parameters,
                )
                for row in await cursor.fetchall():
                    table_name = row.pop("table_name")
                    row["nullable"] = row["nullable"] == "YES"
                    schemas[table_name]["columns"].append(row)
                await cursor.execute(
                    "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS `column`, "
                    "REFERENCED_TABLE_SCHEMA AS referenced_database, "
                    "REFERENCED_TABLE_NAME AS referenced_table, "
                    "REFERENCED_COLUMN_NAME AS referenced_column "
                    "FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = %s "
                    f"AND TABLE_NAME IN ({placeholders}) AND REFERENCED_TABLE_NAME IS NOT NULL "
                    "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION",
                    parameters,
                )
                for row in await cursor.fetchall():
                    table_name = row.pop("table_name")
                    schemas[table_name]["foreign_keys"].append(row)
                return [schemas[name] for name in table_names]

    async def query(self, database: str, sql: str) -> dict:
        self._check_database(database)
        prepared_sql = _prepare_sql(sql, self._databases, self._max_rows)
        started = monotonic()
        async with self._connection() as connection:
            await connection.select_db(database)
            async with connection.cursor() as settings_cursor:
                await settings_cursor.execute(
                    "SET SESSION max_execution_time = %s", (self._query_timeout_ms,),
                )
            cursor = await connection.cursor(aiomysql.SSCursor)
            try:
                await cursor.execute(prepared_sql)
                result = _ResultBuffer(
                    [column[0] for column in cursor.description], self._max_rows, self._max_bytes,
                )
                while (row := await cursor.fetchone()) is not None:
                    if not result.append(row):
                        # SSCursor.close drains unread results. Discard this
                        # connection to keep truncation bounded instead.
                        connection.close()
                        break
            finally:
                if not connection.closed:
                    await cursor.close()
        return {
            "database": database, "sql": prepared_sql,
            "columns": result.columns, "rows": result.rows,
            "row_count": len(result.rows), "truncated": result.truncated,
            "elapsed_ms": round((monotonic() - started) * 1000),
        }
