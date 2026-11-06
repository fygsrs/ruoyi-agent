"""Validate read-only analysis SQL and bound its outer result."""

import sqlglot
from sqlglot import ErrorLevel, exp
from sqlglot.errors import ParseError, TokenError, UnsupportedError


class AnalyticsError(Exception):
    """A query or metadata request cannot be safely completed."""


# These are sqlglot's AST function names, including its normalized date helpers.
# An explicit set also excludes stored functions/UDFs, which can have side effects
# and are outside MySQL's SELECT max_execution_time guarantee.
_SAFE_FUNCTIONS = frozenset("""
    ABS ACOS ASIN ATAN ATAN2 CEIL CEILING COS COT DEGREES EXP FLOOR LN LOG
    LOG2 LOG10 MOD PI POW POWER RADIANS RAND ROUND SIGN SIN SQRT TAN TRUNC
    TRUNCATE
    AVG BIT_AND BIT_OR BIT_XOR COUNT GROUP_CONCAT MAX MIN STDDEV STDDEV_POP
    STDDEV_SAMP SUM VARIANCE VAR_POP VAR_SAMP
    CASE COALESCE IF NULLIF GREATEST LEAST CAST TRY_CAST CONVERT
    CONCAT CONCAT_WS CHAR_LENGTH CHARACTER_LENGTH LENGTH LOWER UPPER LCASE
    UCASE LEFT RIGHT SUBSTRING SUBSTR SUBSTRING_INDEX TRIM LTRIM RTRIM
    REPLACE REVERSE LOCATE INSTR POSITION STRCMP ASCII ORD HEX UNHEX
    FIELD FIND_IN_SET FORMAT
    DATE DATE_ADD DATE_SUB DATE_DIFF DATEDIFF DATE_FORMAT DAY DAYOFMONTH
    DAYOFWEEK DAYOFYEAR WEEK WEEKOFYEAR WEEKDAY MONTH MONTHNAME QUARTER YEAR
    YEARWEEK HOUR MINUTE SECOND MICROSECOND TIME TIME_FORMAT TIME_TO_SEC
    SEC_TO_TIME MAKEDATE MAKETIME LAST_DAY EXTRACT CURRENT_DATE CURRENT_TIME
    CURRENT_TIMESTAMP CURDATE CURTIME NOW SYSDATE UTC_DATE UTC_TIME
    UTC_TIMESTAMP TIMESTAMP TIMESTAMPADD TIMESTAMPDIFF UNIX_TIMESTAMP
    FROM_UNIXTIME STR_TO_DATE TO_DAYS FROM_DAYS TO_SECONDS DATE_TRUNC
    TS_OR_DS_TO_DATE TS_OR_DS_TO_TIMESTAMP TIME_TO_STR STR_TO_TIME
    TIME_TO_UNIX UNIX_TO_TIME
    ROW_NUMBER RANK DENSE_RANK CUME_DIST PERCENT_RANK NTILE LAG LEAD
    FIRST_VALUE LAST_VALUE NTH_VALUE
    JSON_EXTRACT JSON_UNQUOTE JSON_LENGTH JSON_TYPE JSON_CONTAINS
    JSON_CONTAINS_PATH JSON_KEYS JSON_VALID JSON_VALUE JSON_ARRAYAGG
    JSON_OBJECTAGG JSON_ARRAY JSON_OBJECT
    REGEXP_LIKE REGEXP_INSTR REGEXP_REPLACE REGEXP_SUBSTR
""".split())

_FORBIDDEN_NODES = (
    exp.DML, exp.DDL, exp.Command, exp.Into, exp.Lock, exp.Hint,
    exp.Parameter, exp.SessionParameter, exp.Placeholder, exp.PropertyEQ,
)


def _prepare_sql(sql: str, databases: frozenset[str], max_rows: int) -> str:
    """Parse the whole input, validate its AST and cap the outer result."""
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 65536:
        raise AnalyticsError("SQL 必须非空且不超过 65536 个字符。")
    try:
        tokens = sqlglot.tokenize(sql, read="mysql")
        # MySQL executable comments are ignored by ordinary SQL parsers, and
        # optimizer hints can override the session timeout. Token comments do
        # not include text inside string literals.
        if any(token.comments for token in tokens):
            raise AnalyticsError("分析 SQL 不支持注释、optimizer hint 或 MySQL 可执行注释。")
        statements = sqlglot.parse(sql, read="mysql", error_level=ErrorLevel.RAISE)
    except (ParseError, TokenError) as error:
        raise AnalyticsError("SQL 语法无效；仅支持单条 MySQL SELECT 查询。") from error

    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Subquery)):
        raise AnalyticsError("仅支持单条 SELECT、UNION 或 WITH SELECT 查询。")
    statement = statements[0]
    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise AnalyticsError("分析 SQL 禁止写入、锁定读、INTO、变量、会话修改和执行命令。")
        if isinstance(node, exp.Query) and not isinstance(node, (exp.Select, exp.Union, exp.Subquery)):
            raise AnalyticsError("查询仅支持 SELECT 和 UNION。")
        if isinstance(node, exp.Select) and node.args.get("operation_modifiers"):
            raise AnalyticsError("分析 SQL 不支持 SELECT 操作修饰符。")
        if isinstance(node, exp.Table):
            if not isinstance(node.this, exp.Identifier) or node.args.get("catalog"):
                raise AnalyticsError("分析 SQL 仅支持普通业务表或 CTE。")
            if node.db and node.db not in databases:
                raise AnalyticsError("SQL 引用了未配置的数据库。")
        if isinstance(node, exp.Column) and node.db and node.db not in databases:
            raise AnalyticsError("SQL 引用了未配置的数据库。")
        if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
            raise AnalyticsError("分析 SQL 不支持存储函数或限定库名的函数。")
        # sqlglot also models AND/OR/XOR and EXISTS as Func. They are SQL
        # structure rather than named function calls; their children still
        # receive the same validation during this walk.
        if isinstance(node, exp.Func) and not isinstance(node, (exp.Connector, exp.SubqueryPredicate)):
            name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name()
            if name not in _SAFE_FUNCTIONS:
                raise AnalyticsError(f"分析 SQL 不支持函数 {name}。")

    limit = statement.args.get("limit")
    row_limit = max_rows + 1
    if limit is not None:
        value = limit.expression
        if not isinstance(value, exp.Literal) or not value.is_int:
            raise AnalyticsError("LIMIT 必须使用非负整数。")
        row_limit = min(int(value.this), row_limit)
    statement.set("limit", exp.Limit(expression=exp.Literal.number(row_limit)))
    try:
        # Execute the parsed representation rather than sending unchecked
        # source syntax whose interpretation may differ between parsers.
        return statement.sql(dialect="mysql", comments=False, unsupported_level=ErrorLevel.RAISE)
    except UnsupportedError as error:
        raise AnalyticsError("SQL 包含不支持的 MySQL 查询语法。") from error
