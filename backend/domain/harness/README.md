# backend/domain/harness/

项目运行状态机。

## 状态定义

```
READY                 立项 finalize 后未启动
  → RUNNING           用户点开始 / 继续
       ⇄ PAUSED       用户暂停 / 项目运行中关窗触发
  → COMPLETED                        所有 Task done + final_qa.verdict == pass
  → COMPLETED_WITH_WARNINGS          ... + final_qa.verdict == warn
  → COMPLETED_WITH_ISSUES            ... + final_qa.verdict == fail
  → ABORTED                          用户主动放弃（删项目 = 不进此状态，直接物理删除）
```

## 转移规则

| from → to | 触发 | service 调用 |
|---|---|---|
| READY → RUNNING | 用户点"开始" | workflow_svc.start() |
| RUNNING → PAUSED | 用户点"暂停" / 关窗触发 | workflow_svc.pause() |
| PAUSED → RUNNING | 用户点"继续" | workflow_svc.resume() |
| RUNNING → COMPLETED* | 全部 Task done + final_qa 完成 | workflow_svc 自动转移 |
| RUNNING → ABORTED | 强制中断超阈值 / 用户确认放弃 | workflow_svc.abort() |

## 任务级状态机（在 §4 tasks.status）

`pending → running → done`
              ↘ failed / paused / aborted / validation_failed / blocked

- `blocked`：依赖的上游处于失败/中断状态
- `validation_failed`：Pydantic 校验失败超 `max_retry` 次

## 文件清单（Phase 4 创建）

- `state_machine.py` — 状态枚举 + 转移函数（纯函数）
- `dispatcher.py` — DAG 调度逻辑：找就绪 Task、并发派发（受 `task_concurrency_limit`）、fork-join 等待
- `events.py` — Domain Event 定义

## 测试

- 用 Mock Port 跑全状态流转（pytest-asyncio）
- 覆盖暂停语义、强制中断、rerun 级联、validation_failed 自动重试、`Agent.max_retry` 预算
