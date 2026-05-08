# backend/domain/qa/

DAG 健壮性 + Task 输出 schema 校验调度。

## 职责拆分

- **领域逻辑（本目录）**：DAG 校验、schema 校验调度策略、提取 prompt 构造
- **实际验证（infra）**：Pydantic / jsonschema 库调用（infra/repo 或 infra/llm 中）

## 文件清单（Phase 4 / Phase 5 创建）

| 文件 | 职责 |
|---|---|
| `dag_validator.py` | 立项 finalize 阶段的 DAG 校验：① 拓扑排序检测环路 ② 引用完整性（deps 中 task_id 都存在） ③ 连通性（无孤立节点；至少有一个 entry） |
| `schema_validator.py` | JSON Schema 自身合法性校验（用 jsonschema 库调用） |
| `output_extractor.py` | 协调"二次提取"流程：构造提取 prompt（含 schema + agent free text + 历史报错）→ 调 LLMPort → Pydantic 验证 → 报错回灌（重试时） |
| `final_qa_builder.py` | 自动在蓝图末端插入 `kind=final_qa` Task 的工厂函数（如果立项 LLM 漏掉） |

## 重试预算

- 自动重试（含 validation_failed）计入 `Agent.max_retry`
- 用户手动介入对话窗口的重试**不计入**
- 累积上下文：原 prompt + 上次 Agent 输出 + 上次错误详情 + 重新生成指令
