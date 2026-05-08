# backend/tests/

后端测试。

## 测试金字塔

| 层 | 范围 | 覆盖率目标 |
|---|---|---|
| 单元 | `domain/` 纯函数、状态机转移、`services/` 用例 | ≥ 70% |
| 集成（Port Mock） | service ↔ Mock Port 协作 | 关键流程必覆盖 |
| 集成（真 SQLite） | repo 实现 ↔ `:memory:` SQLite | 关键查询必覆盖 |
| 端到端 | API → service → domain → infra | 不在本目录；走 `tests/`（项目根 E2E） |

## 工具栈

- pytest + pytest-asyncio（async 路径）
- pytest-cov（覆盖率）
- httpx + ASGI test client（API 集成测试）
- Mock Port 用 dataclass + protocol 实现，不引 unittest.mock 的 MagicMock

## 文件组织（按领域）

```
tests/
├─ conftest.py             # 共享 fixture：app/container/db
├─ unit/
│  ├─ domain/
│  │  ├─ test_harness_state_machine.py
│  │  ├─ test_dag_validator.py
│  │  └─ ...
│  └─ services/
│     ├─ test_workflow_svc.py
│     └─ ...
├─ integration/
│  ├─ test_api_project.py
│  ├─ test_repo_sqlite.py
│  └─ ...
└─ fixtures/
   └─ schema_samples.py    # 测试用 output_schema 范本
```

## 命令

```bash
cd backend
pytest                                 # 全部
pytest tests/unit                      # 仅单元
pytest -k "harness"                    # 关键字过滤
pytest --cov=backend --cov-report=html # 覆盖率
```
