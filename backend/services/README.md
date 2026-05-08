# backend/services/

业务层：编排领域逻辑，调度 Port 实现。

## 核心约束

- service 是"用例"层（use cases），每个 service 对应一个业务领域
- 不直接接触 SQLite / HTTP / WS / 文件系统；通过 ports/ 抽象
- 不写 HTTP/WS 协议细节；那是 api/ 的事

## 文件清单

| 文件 | 职责 |
|---|---|
| `project_svc.py` | 项目 CRUD、复制（仅 task 结构 + Agent 绑定 + Crew/Flow 选择，不带 root_path/进度/IO/inception session）、删除（二次确认）、卡片分页、根目录绑定 |
| `inception_svc.py` | 建项目对话：管理立项会话、调用 LLM 拆解任务、本地文件索引、按任务数选择执行结构、调用 `agent_factory`/`crew_factory` Tool 动态生成缺失资源、产出蓝图（含 output_schema 与 final_qa Task）|
| `workflow_svc.py` | 启动/暂停/恢复 Harness；暂停 = 当前任务跑完、截断后续链；强制中断逃生门；rerun 级联；DAG 调度（并发上限可配，默认 3）；fork-join 严格等所有 deps 完成 |
| `mcp_svc.py` | MCP 服务器池：启动、心跳、`discovered_tools` 同步、强制全量重连；不直接和 Agent 打交道，仅作为后台资源 |
| `llm_svc.py` | LLM 配置（一对多 model）、Token 用量轮询适配（百分比/M 数/绿红圆点；调不到额度时派最小请求探活）、30s 自动+手动刷新、双默认（立项/Agent） |
| `agent_svc.py` | Agent 模板 CRUD；运行时把 Agent.tool_ids 关联的 Tool 实例化注入 CrewAI Agent |
| `crew_svc.py` | Crew CRUD（队名/process/agent_ids） |
| `tool_svc.py` | Tool CRUD；扫描 `src/tools/` → import → 找 BaseTool 子类 → 转 schema 入库；checksum 校验；首次发现弹窗；MCP 包装 Tool 与用户 Tool 同一存储 |
| `permission_svc.py` | 系统权限白名单（9 个布尔开关）；运行时拦截器接到 Tool/MCP 真正调用，按"是否被禁用"短路返回；MVP 不做路径白名单 |
| `log_svc.py` | 日志查询、按 source（多终端 tab）分流、归档；JSON 行格式 |

## 依赖关系

- service 之间可互相调用，但避免循环（DI 容器初始化时检测）
- service → ports；服务通过 Port 拿到 LLM / MCP / Repo / Interaction 实现
