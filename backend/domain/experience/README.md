# backend/domain/experience/

经验库（Agent 长期记忆的领域抽象）。

## 职责

- 与 CrewAI 内建 long-term memory 对接
- Agent.memory_path（默认 `data/memory/{agent_id}/`）的领域逻辑
- 经验摘要写入与按 tag 相关性匹配读取

## 文件清单（Phase 4 创建）

| 文件 | 职责 |
|---|---|
| `repository.py` | 经验记录的 CRUD 抽象（依赖 RepoPort）|
| `matcher.py` | tag 相关性匹配（不调 LLM，纯字符串/集合算法）|
| `injector.py` | 在 Agent 执行前从经验库选择 top-N 注入到 prompt |

## v2 → v3 简化

- v2 有独立的"技能积累池"（skill_pool 表），v3 简化为 CrewAI 内建 memory + 本目录的轻量索引
- 不再做向量化嵌入（embeddings）；如需更复杂的检索，将来作为可选 RAG 模块单独建（不在 MVP）
