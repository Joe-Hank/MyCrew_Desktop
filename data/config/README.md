# data/config/

应用配置文件。

## 关键文件

### `app.yaml`（启动加载 STEP 1 读取）

```yaml
# 示例（Phase 2 落地）
theme: dark                          # light | dark | system
window:
  width: 1280
  height: 800
  maximized: false
last_active:
  page: home                         # home | tasks | team | settings
  project_id: null
log_drawer:
  expanded: false
  active_tab: app                    # app | mcp:<server_name> | agent
auto_start_mcp:
  - filesystem
  - blender
inception_drawer_width_pct: 37       # 黄金分割可拖拽记忆
```

## 写入策略

- UI 操作（如改主题、调抽屉宽度）→ debounce 1s 后写
- `app_settings` 表中的键值（`default_inception_model` 等）也镜像写入此处用于冷启动加速

## 与 SQLite app_settings 表的关系

- SQLite 是真相源（结构化、事务）
- app.yaml 是冷启动快照（避免启动期等 SQLite 初始化才能渲染）
- 二者存在不一致时以 SQLite 为准；启动后异步对齐

## 读取约定

- backend/bootstrap/lifespan.py STEP 1 加载
- 失败时降级为内置默认值，不阻断启动
