# backend/domain/

领域层：纯业务逻辑，零 IO。

## 核心约束

- **不**直接调任何外部系统（LLM / DB / MCP / 文件）
- 所有副作用通过 `ports/` 接口抽象
- 类型纯粹：dataclass / Pydantic / TypedDict
- 单元测试用 Mock Port 即可全覆盖

## 子模块

| 子模块 | 职责 |
|---|---|
| `harness/` | 项目运行状态机（READY → RUNNING ⇄ PAUSED → completed/warnings/issues/aborted） |
| `qa/` | DAG 健壮性校验（拓扑/引用完整性/连通性）+ Task 输出 schema 校验调度（实际 Pydantic 验证下沉到 infra） |
| `experience/` | 经验库读写、tag 相关性匹配（CrewAI long-term memory 的领域抽象） |
| `events.py` | Domain Event 定义（dataclass）：ProjectStateChanged / TaskStarted / TaskCompleted / TaskFailed / ValidationFailed / etc. |

## v3 状态机说明（与 v2 不同）

v2 的 Harness 状态机有 INIT/PLANNING/REVIEW/EXECUTING/QA/FINAL_QA 阶段。v3 拆解为：

- **PLANNING/REVIEW** → 由 `inception_svc` 接管（项目建好前，不属本状态机）
- **QA** → 每个 Task 的 output_schema 校验（不是单独阶段）
- **FINAL_QA** → DAG 末端的 `final_qa` Task（也不是单独阶段）

所以 v3 项目状态机只剩：
```
DRAFT (in inception, 不在本目录)
  ↓ finalize
READY → RUNNING ⇄ PAUSED
                    ↓
        COMPLETED / COMPLETED_WITH_WARNINGS / COMPLETED_WITH_ISSUES / ABORTED
```

> `domain/planner/` 在 v2 存在，v3 已被 `services/inception_svc.py` 接管，**不在本目录创建**。
