# frontend/src/queries/

React Query hook，**仅用于服务端态**（项目/任务/MCP/LLM/日志/配置等）。

## 命名规范

- 一个 hook 一个文件：`useXxxQuery.ts`
- 变更操作：`useXxxMutation.ts`

## 必备 hook 清单

| hook | 端点 | WS 事件 patch |
|---|---|---|
| `useProjectsQuery` | `GET /projects?page=&size=4` | `project.*` |
| `useProjectQuery(id)` | `GET /projects/:id` | `project.*` |
| `useTasksQuery({projectId})` | `GET /tasks?project_id=` | `task.*` |
| `useTaskIoQuery({id, dir})` | `GET /tasks/:id/io?direction=` | （on demand） |
| `useMcpStatusQuery` | `GET /mcp/servers` | `mcp.connected` `mcp.disconnected` |
| `useLlmProvidersQuery` | `GET /llm/providers` | — |
| `useLlmQuotaQuery` | `GET /llm/quota` | `llm.quota_changed` |
| `useAgentsQuery` `useCrewsQuery` `useToolsQuery` | `GET /agents` `/crews` `/tools` | `tool.changed` `tool.discovered` |
| `usePermissionsQuery` | `GET /permissions` | — |
| `useLogsQuery` | `GET /logs?source=&level=&since=` | `log.append` |
| `useInceptionsQuery` | `GET /inceptions` | `inception.*` |

## WS patch 模式

```ts
// 通用模式
useEvent('task.completed', (payload) => {
  queryClient.setQueryData(['tasks', payload.project_id], (old) =>
    old?.map((t) => t.id === payload.task_id ? { ...t, status: 'done' } : t)
  );
});
```

详见 `hooks/useEvent.ts` 实现。

## staleTime / cacheTime 约定

- 列表型（项目列表 / Agent 列表）：`staleTime: 30s, cacheTime: 5min`
- 配额型（Token 监控）：`staleTime: 30s, refetchInterval: 30s`（PRD 要求 30s 自动刷新）
- 详情型（项目详情 / 任务 IO）：`staleTime: Infinity`，由 WS 事件主动 patch
