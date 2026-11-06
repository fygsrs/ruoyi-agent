# 若依集成补丁

这两份补丁保存 Agent 聊天、用户审核、查询约束和知识库页面所需的若依改动。若依源码从公开上游获取，补丁按下列提交生成。

| 补丁 | 公开上游 origin | 基准提交 | 文件数 |
| --- | --- | --- | --- |
| `ruoyi-vue3.patch` | [yangzongzhuan/RuoYi-Vue3](https://github.com/yangzongzhuan/RuoYi-Vue3.git) | `838965c5a18d2c61b73ec30c6e288057aaa08b63` | 12 |
| `ruoyi-java.patch` | [yangzongzhuan/RuoYi-Vue](https://github.com/yangzongzhuan/RuoYi-Vue.git) | `a51a838b71b446ea27256900efe7ed2faa2a02fd` | 7 |

补丁包含相对于各自基准提交的完整定制代码；文件路径均相对于对应的若依仓库根目录。

## 应用补丁

在本项目根目录执行以下 PowerShell 命令。`sources` 下的两个仓库由本地独立管理。

```powershell
$agentRoot = (Get-Location).Path

git clone https://github.com/yangzongzhuan/RuoYi-Vue3.git sources/RuoYi-Vue3
git -C sources/RuoYi-Vue3 checkout 838965c5a18d2c61b73ec30c6e288057aaa08b63
$frontendPatch = Join-Path $agentRoot 'integrations/ruoyi-vue3.patch'
git -C sources/RuoYi-Vue3 apply --check $frontendPatch
git -C sources/RuoYi-Vue3 apply $frontendPatch

git clone https://github.com/yangzongzhuan/RuoYi-Vue.git sources/RuoYi-Vue
git -C sources/RuoYi-Vue checkout a51a838b71b446ea27256900efe7ed2faa2a02fd
$javaPatch = Join-Path $agentRoot 'integrations/ruoyi-java.patch'
git -C sources/RuoYi-Vue apply --check $javaPatch
git -C sources/RuoYi-Vue apply $javaPatch
```

已有源码时，从上述 `checkout` 步骤开始，并先保存现有改动。使用其他上游提交时先执行 `git apply --check`，按差异处理冲突。

前端补丁在 `package.json` 增加 `eventsource-parser` 4.1.3。应用后进入 `sources/RuoYi-Vue3` 执行 `npm install`，再执行 `npm run dev -- --port 5173` 或 `npm run build:prod`。Java 补丁按若依原有 Maven 构建流程编译。

## 改动范围

前端包括 `package.json`、`vite.config.js`、`src/api/agent/`、`src/composables/useAgentChat.js` 和 `src/views/agent/`，提供聊天流、用户操作审核、查询约束管理、知识库管理和引用来源预览。

Java 包括 `AgentQueryBlockRule` 的控制器、领域对象、Mapper、Service 和 MyBatis XML，以及 `SysUserMapper.xml` 的昵称筛选条件。用户查询沿用若依原有的权限与数据范围。

## 菜单与权限

通过若依的菜单与角色管理配置以下页面，并分配给需要访问的角色。

| 页面 | 路由路径 | 组件路径 | 组件名称 |
| --- | --- | --- | --- |
| Agent 聊天 | `/agent` | `agent/chat/index` | `AgentChat` |
| 查询约束 | `/analytics-rules` | `agent/analytics-rules/index` | `AnalyticsRules` |
| 知识库 | `/knowledge` | `agent/knowledge/index` | `AgentKnowledge` |

聊天与知识库读取要求有效的若依登录身份。知识库资料由已登录用户共享；维护操作分配以下按钮权限，并由 Python API 再次校验：

| 操作 | 权限标识 |
| --- | --- |
| 创建、修改、删除知识库 | `knowledge:base:add`、`knowledge:base:edit`、`knowledge:base:remove` |
| 上传、重处理、删除文档 | `knowledge:document:upload`、`knowledge:document:reprocess`、`knowledge:document:remove` |
| 新增、修改、删除用户 | `system:user:add`、`system:user:edit`、`system:user:remove` |
| 查询用户及审核选项 | `system:user:query`、`system:user:list` |

查询约束菜单使用 `agent:analyticsRules:list`。Java `/agent/analytics/rules` 的所有读写接口还会检查若依的真实超级管理员身份；菜单授权不会放宽该限制。

查询约束功能需要在若依 MySQL 数据库准备 `agent_query_block_rule` 表，其字段契约如下。按本地环境初始化表和规则后再使用该页面。

| 字段 | 要求 |
| --- | --- |
| `id` | 自增整数主键，Mapper 使用生成的主键 |
| `database_name`、`table_name`、`column_name` | 最多 64 个字符的非空名称 |
| `remark` | 最多 200 个字符的备注 |
| `create_by`、`update_by` | 若依操作用户名 |
| `create_time`、`update_time` | 创建、修改时间 |

规则支持 `库/*/*`、`库/表/*` 和 `库/表/字段`；数据库名不能为 `*`，表名为 `*` 时字段名也必须为 `*`。

## API 代理与认证

前端开发代理由补丁中的 `vite.config.js` 配置：

| 浏览器路径 | 本地目标 | 路径处理 |
| --- | --- | --- |
| `/agent-api/...` | `http://127.0.0.1:8000`，Python Agent API | 移除 `/agent-api` 前缀 |
| `/dev-api/...` | `http://127.0.0.1:8080`，若依 Java API | 移除 `/dev-api` 前缀 |

聊天、审核与知识库调用 Python API；查询约束调用 Java `/agent/analytics/rules`。请求使用当前若依登录令牌的 `Authorization: Bearer ...`，Python 通过 Java `/getInfo` 验证身份和权限。

生产反向代理保持相同的路径映射，转发 Authorization 请求头，允许聊天 SSE 持续流式返回，并为知识库上传配置至少 50 MB 的请求体上限。知识库原件与图片经认证接口读取。

Python 服务的模型、数据库和解析服务配置参考本项目根目录的 `.env.example`。实际凭据放在本地 `.env` 或运行环境中，前端仅使用若依登录令牌。

## 补丁验证

生成时已在当前定制源码上执行以下只读检查，确认补丁与文件内容一致：

```powershell
git -C sources/RuoYi-Vue3 apply --reverse --check $frontendPatch
git -C sources/RuoYi-Vue apply --reverse --check $javaPatch
```

两份补丁均通过检查，生成前后的源仓库状态和 Git 索引保持一致。补丁共 19 个文件，全部属于上面列出的代码范围。
