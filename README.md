# RuoYi Agent

使用 Python 3.12、uv、FastAPI 和 LangChain，模型通过 `init_chat_model` 初始化，默认 `deepseek-flash`。
若依 Vue 3 页面自行解析 SSE，不依赖 LangChain 前端 SDK。

## 代码结构

Python 源码位于 `src/ruoyi_agent`，按聊天、用户管理、数据库分析和知识库分包：

```text
ruoyi_agent/
├── app.py                # FastAPI 应用与资源生命周期
├── agent.py              # 模型、提示词与动态工具筛选
├── auth.py               # 若依令牌认证
├── permissions.py        # 共享权限判断
├── context.py            # AgentContext：本轮身份与依赖
├── config.py             # 模型配置
├── chat/
│   ├── routes.py         # HTTP 路由与 SSE 响应
│   ├── schemas.py        # 聊天与审核恢复请求
│   └── service.py        # 会话运行、消息恢复与人工审核恢复
├── users/
│   ├── tools.py          # 用户工具与执行编排
│   ├── schemas.py        # 用户草稿、命令与审核模型
│   └── review.py         # 用户表单与审核流程
├── analytics/
│   ├── tools.py          # 结构发现和查询工具
│   ├── executor.py       # MySQL 连接、元数据与查询执行
│   ├── sql_policy.py     # 只读 SQL 校验与改写
│   └── notes.md          # 若依业务口径
├── knowledge/
│   ├── routes.py         # 知识库、文档和受保护图片接口
│   ├── service.py        # 原件保存与检索范围
│   ├── store.py          # PostgreSQL 元数据与持久任务队列
│   ├── worker.py         # 解析、建索引、重处理与删除
│   ├── parser.py         # MinerU 官方云端 SDK
│   ├── splitting.py      # LangChain 分片与来源元数据
│   ├── vectorstore.py    # LangChain Milvus 混合检索与服务端重排
│   ├── tools.py          # search_knowledge 工具
│   ├── citations.py      # 聊天引用快照
│   ├── schemas.py        # HTTP 输入和输出模型
│   └── config.py         # 知识库配置
├── ruoyi_client.py       # Java API 调用与响应校验
├── persistence.py        # 会话资料、并发锁与操作账本
├── tools.py              # 通用时间工具
├── cli.py                # 命令行入口
└── server.py             # Windows 事件循环配置
```

工具保持函数形式；各业务模块声明工具与所需权限，`agent.py` 统一组装并按当前用户筛选。

若依前端源码位于 `sources/RuoYi-Vue3`，包含聊天、查询约束和知识库管理页面；
Java 源码位于 `sources/RuoYi-Vue`，包含查询约束接口及用户昵称筛选等配套修改。
这两个目录已包含本项目的集成代码，可直接安装依赖和构建。

## 启动

```powershell
cd ruoyi-agent
uv sync
Copy-Item .env.example .env
# 填写 .env 后启动 API
uv run uvicorn ruoyi_agent.app:create_app --factory --workers 1 --loop ruoyi_agent.server:loop_factory --host 127.0.0.1 --port 8000
```

- 若依聊天页面：<http://127.0.0.1:5173/agent>
- 若依知识库页面：<http://127.0.0.1:5173/knowledge>
- 若依 Java：<http://127.0.0.1:8080>
- Agent API：<http://127.0.0.1:8000>，`GET /health`

`.env` 保存模型密钥、若依地址、数据库和 Milvus 连接配置，已加入 Git 忽略；参考 `.env.example` 填写实际值。
需要已运行的若依 Java 服务、PostgreSQL、MySQL 只读账号和支持内置向量化、重排的 Milvus 服务。

若依前端使用 Node.js 和 npm，在独立终端启动：

```powershell
cd sources/RuoYi-Vue3
npm install
npm run dev -- --port 5173
```

Vite 将 `/dev-api` 转发到本机 Java 的 8080 端口，将 `/agent-api` 转发到本机 Python 的 8000 端口。
两个代理地址在 `sources/RuoYi-Vue3/vite.config.js` 中配置。

Java 使用 JDK 17 和 Maven。从仓库根目录构建、启动：

```powershell
mvn -f sources/RuoYi-Vue/pom.xml -DskipTests package
java -jar sources/RuoYi-Vue/ruoyi-admin/target/ruoyi-admin.jar --spring.config.additional-location=file:../ruoyi-local-config/
```

启动前，按自己的环境在仓库外的 `../ruoyi-local-config/` 中准备 `application.yml` 和
`application-druid.yml`，填写若依 MySQL、Redis 和本机文件目录配置；实际凭据不纳入源码提交。
首次使用若依还需初始化其数据库，并在菜单管理中配置本项目页面及权限。

另开一个终端启动知识库后台进程：

```powershell
uv run python -m ruoyi_agent.knowledge.worker
```

Windows 下使用项目提供的 Selector 事件循环，以支持 Psycopg 异步连接。
命令行示例仍可独立运行，不访问聊天数据库：

```powershell
uv run ruoyi-agent "现在几点？"
```

## 会话与身份

每次请求携带 `Authorization: Bearer <若依令牌>`。Python 调用 Java `/getInfo` 验证登录身份和权限，
访问会话时再检查会话所属用户。令牌和 HTTP 客户端只放在本次运行上下文，不进入模型和检查点。
业务工具继续使用当前用户的令牌调用 Java，由若依完成最终权限和数据范围校验。

PostgreSQL 保存 LangGraph 检查点和应用表 `agent_threads`、`agent_operations`。
页面记住当前用户的会话编号，刷新后从服务端恢复消息和待审核表单；前端只发送本轮新增消息。
不同用户不能读取、继续或审核彼此的会话。当前服务使用单进程、单事件循环，按 `thread_id` 共享 `asyncio.Lock`，
同一会话正在运行时拒绝重复请求；不同会话可并发，不会因为锁而长期占用数据库连接。
本轮完成、暂停审核、异常或取消后释放锁，并清理对应的内存锁条目。

接口：

| 接口 | 用途 |
| --- | --- |
| `POST /chat`，`{"action":"greet"}` | 创建会话并问候当前用户 |
| `POST /chat`，`{"action":"chat","thread_id":"UUID","content":"消息"}` | 在已有会话发送一条消息 |
| `GET /chat` | 当前用户最近 100 个会话 |
| `GET /chat/{thread_id}` | 恢复可见消息及待审核表单 |
| `DELETE /chat/{thread_id}` | 删除当前用户的会话及其聊天检查点，成功返回 204 |
| `POST /chat/resume` | 提交人工审核决定 |
| `GET /users/options` | 根据当前用户权限读取部门、角色和岗位选项 |

流式事件为 `thread`、`delta`、`sources`、`review_required`、`done`、`error`。
`review_required` 表示本轮已暂停，`done` 表示运行完成，两者都结束本次 SSE。
左侧会话列表支持切换、新建和删除；正在处理的会话不能删除。删除会话不会撤销已执行的用户操作，业务操作账本继续保留。

审核请求示例：

```json
{
  "thread_id": "会话 UUID",
  "interrupt_id": "服务端返回的审核编号",
  "decision": "approve",
  "fields": {"userName": "zhangsan", "nickName": "张三", "roleIds": [], "postIds": []}
}
```

`decision` 支持 `approve`、`reject`、`feedback`；反馈使用 `feedback` 文本字段。
过期或已处理的审核不能再次执行。拒绝和文字反馈均不写入 Java。

## 用户管理

三个工具为 `create_user`、`update_user`、`delete_user`，分别依赖若依的
`system:user:add`、`system:user:edit`、`system:user:remove`。
无对应权限的工具不会提供给模型，工具内部也校验权限。
读取详情和表单选项还需要相应的 `system:user:query`、`system:user:list` 权限。

只读工具 `query_user_options` 返回当前用户可选的部门树、岗位和角色。用户使用名称或简称时，
模型先查询真实候选，再理解其意图并将 ID 预填到审核表单；同名或含糊的选择通过表单提示人工确认。
后端继续校验最终选择，批准前不写入若依。

已知部分信息就可以生成表单，人工补齐、编辑和批准后再执行；也可以拒绝或发送修改要求。
修改和删除支持直接说登录账号或昵称，模型通过只读工具 `query_users` 查询真实目标；
明确账号时完全匹配，昵称重名或目标含糊时先确认账号。编号只在内部使用，不要求用户提供。
未提供目标时先在表单填写登录账号，由服务端查找后展示完整审核。

- 新增：初始密码在批准后读取若依系统配置，不写入模型、审核表单或操作记录。
- 修改：保留未修改的角色、岗位和其他资料；不修改登录账号和密码。原资料在等待审核期间变化时要求重新审核。
- 删除：一次删除一个用户，禁止删除超级管理员和当前登录用户。
- 执行：记录操作状态与结果；已成功操作返回保存结果，超时或中断导致结果不明时要求到若依核查，不自动重复写入。

模型或连接出错时，页面先恢复已保存状态。检查点显示上轮运行未完成时要求新建对话；
涉及用户写入时先检查若依中的实际结果。

## 数据库分析

仅若依真实超级管理员（`userId=1`）可使用 `get_analytics_schema` 和 `query_analytics`。
Python 通过独立 MySQL 只读账号查询，凭据保存在 `.env` 的 `ANALYTICS_MYSQL_*` 配置中。
数据库地址及连接方式由运行环境配置，会话保存在 PostgreSQL，MySQL 分析查询使用独立连接池。

`get_analytics_schema` 无参数时返回可用库，指定 `database` 时列出表，可用 `keyword` 筛选，
再通过 `tables` 批量读取字段、注释和外键。结构实时读取，不维护完整结构副本。
少量若依业务口径在 `src/ruoyi_agent/analytics/notes.md`，随相关结构提供给模型。

若依新增菜单“查询约束”（`/analytics-rules`），通过 Java `/agent/analytics/rules` 管理
`agent_query_block_rule` 表，需要在若依环境中配置对应菜单、权限和业务表。
三种规则分别是 `库/*/*`、`库/表/*`、`库/表/字段`。
未命中规则且只读账号有权访问的对象默认开放，新增对象同样适用。

规则用于过滤结构并指导模型生成 SQL；执行器不实现字段黑名单的强制拦截，
不将这套提示约束当作数据库字段权限。执行器限制单条只读分析查询、函数、超时、行数与结果字节数；
返回实际 SQL 和截断标记。规则读取失败即停止工具调用。

## 知识库

若依菜单“知识库”（`/knowledge`）支持知识库增删改、文件上传、处理状态、失败重试、重新索引和删除。
菜单组件为 `agent/knowledge/index`，页面和维护按钮按若依角色权限分配。
所有已登录用户共享资料，聊天模型自动获得只读工具 `search_knowledge`，默认检索全部已就绪文档。
新增、修改、删除知识库分别需要 `knowledge:base:add/edit/remove`；上传、重处理、删除文档分别需要
`knowledge:document:upload/reprocess/remove`。Python 在每个请求通过 Java 获取当前权限。

PDF、Word、PowerPoint、Excel 和图片使用官方 `mineru-open-sdk` 云端解析；UTF-8 TXT、Markdown 直接读取。
单文件最多 50 MB。配置 `.env` 中的 `MINERU_API_TOKEN`，原件、Markdown、结构 JSON、图片保存在
`data/knowledge/{kb_id}/{document_id}/`，可用 `KNOWLEDGE_DATA_DIR` 指定持久目录。
页面通过携带若依 Bearer 的 Python 接口读取原件和图片；磁盘目录不公开。

PostgreSQL 的 `agent_knowledge_bases/docs/assets/jobs` 保存资料和任务状态，后台流程不使用 LangGraph。
独立后台进程启动时恢复未完成任务；任务失败后可在页面手动重试。
运行 `uv run python -m ruoyi_agent.knowledge.worker` 启动，处理结果记录在任务表，错误也输出到进程日志。
当前只运行一个后台 worker；扩展多个 worker 前需要增加任务租约和恢复归属。

LangChain 按页和章节分片，单片约 1000 字符、重叠 150 字符，保留文档名、版本、页码和图片 ID。
`langchain-milvus` 写入独立集合 `ruoyi_knowledge_chunks`，通过 Milvus 内置函数调用阿里云
`qwen3.7-text-embedding-flash`（1024 维），结合 BM25 召回，再用 `qwen3.7-text-rerank` 服务端重排。
Milvus 服务端需配置 DashScope embedding provider 和 ali rerank provider 的模型凭据；其他集合不用于本功能。
查询范围限定为已就绪文档，重处理或删除开始后立即退出检索；旧版本不会作为当前依据返回。

聊天回答用 `[1]` 标记引用，前端可展开原文、页码、图片并查看原文件。
引用摘录随 ToolMessage 保存在 LangGraph 检查点中，恢复历史聊天时仍可查看；原文删除后下载链接返回 404。
删除任务依次清理 Milvus 向量、文档磁盘目录、PostgreSQL 文档与资产记录；清理失败保留状态和错误供重试。
内部任务日志保留处理结果，删除文档不会清除历史聊天里的引用摘录。

对外接口仅包括：

| 接口 | 用途 |
| --- | --- |
| `GET /knowledge/bases` | 共享知识库列表 |
| `POST /knowledge/bases` | 创建知识库 |
| `PATCH /knowledge/bases/{kb_id}` | 修改名称和说明 |
| `DELETE /knowledge/bases/{kb_id}` | 异步删除知识库及文档 |
| `GET /knowledge/bases/{kb_id}/documents` | 按 `page`、`page_size` 分页查看文档及状态 |
| `POST /knowledge/bases/{kb_id}/documents` | multipart `file` 上传并入队 |
| `POST /knowledge/documents/{document_id}/reprocess` | 重新解析并索引 |
| `DELETE /knowledge/documents/{document_id}` | 异步删除文档及关联内容 |
| `GET /knowledge/documents/{document_id}/file` | 原件 |
| `GET /knowledge/assets/{asset_id}` | 解析图片 |

前端统一使用既有 `/agent-api` 代理，无需新增对外端口。原件目录需持久保存，备份时与 PostgreSQL、Milvus 一并处理。

## 验证

本地已验证身份隔离、会话归属、审核恢复与重复提交、输入边界、Java 错误、
真实 LangGraph 中断恢复、字段保留及取消连接，以及知识库上传、云端解析、检索、重处理和删除。
可在 `sources/RuoYi-Vue3` 执行 `npm run build:prod` 验证前端构建，
Java 构建使用上面的 Maven 命令。

## 上游与许可

前端基于 [RuoYi-Vue3](https://github.com/yangzongzhuan/RuoYi-Vue3)，Java 基于
[RuoYi-Vue](https://github.com/yangzongzhuan/RuoYi-Vue) 的 `springboot3` 分支。
两个上游项目均采用 MIT 许可；原有作者版权声明及 `LICENSE` 保留在对应 `sources/` 目录中。
