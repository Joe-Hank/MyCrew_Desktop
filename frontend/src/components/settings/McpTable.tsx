import { useMcpServers, useDeleteMcpServer, useConnectMcpServer, useDisconnectMcpServer } from "../../queries/useMcpQuery";
import RowActionsMenu from "../common/RowActionsMenu";
import QueryErrorState from "../common/QueryErrorState";

const GRID = "grid-cols-[20px_1.2fr_0.8fr_1fr_0.8fr_0.5fr_0.8fr_60px]";

interface McpRow {
  id: string;
  name: string;
  transport: string;
  command?: string;
  url?: string;
  host?: string;
  port?: number;
  enabled?: boolean;
  runtime_status?: string;
}

function statusInfo(rt?: string, enabled?: boolean): { dot: string; label: string } {
  if (!enabled) return { dot: "#cbd5e1", label: "已禁用" };
  switch (rt) {
    case "connected":
      return { dot: "#10b981", label: "运行中" };
    case "connecting":
      return { dot: "#facc15", label: "连接中" };
    case "error":
      return { dot: "#ef4444", label: "错误" };
    case "disconnected":
    default:
      return { dot: "#cbd5e1", label: "未连接" };
  }
}

function McpTable({ onEdit }: { onEdit: (s: Record<string, unknown>) => void }) {
  const { data: servers, isLoading, isError, error, refetch, isFetching } = useMcpServers();
  const deleteMut = useDeleteMcpServer();
  const connectMut = useConnectMcpServer();
  const disconnectMut = useDisconnectMcpServer();

  const rows = (servers ?? []) as unknown as McpRow[];

  // Show "连接中" immediately when the user clicks 启用 — the backend
  // POST blocks until the underlying MCP handshake settles, and during
  // that window the row's runtime_status doesn't update yet. Tracking
  // the pending-mutation's id lets us paint the in-flight state right
  // away. Same trick for 停止 → "断开中".
  const pendingConnectId = connectMut.isPending
    ? (connectMut.variables as string | undefined)
    : undefined;
  const pendingDisconnectId = disconnectMut.isPending
    ? (disconnectMut.variables as string | undefined)
    : undefined;

  if (isLoading) {
    return <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>加载中...</div>;
  }

  if (isError) {
    return (
      <QueryErrorState
        title="读取 MCP 服务器失败"
        error={error}
        onRetry={() => refetch()}
        isFetching={isFetching}
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-xl bg-white" style={{ border: "1px solid var(--color-border-soft)" }}>
      <div
        className={`grid ${GRID} items-center gap-2 px-5 py-3`}
        style={{ borderBottom: "1px solid var(--color-border-soft)" }}
      >
        <span />
        {["名称", "传输协议", "连接参数", "主机", "端口", "状态", "操作"].map((c) => (
          <span key={c} className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>
            {c}
          </span>
        ))}
      </div>

      {rows.length === 0 ? (
        <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>
          暂无 MCP 服务器
        </div>
      ) : (
        rows.map((s) => {
          // Override the persisted runtime_status with an in-flight
          // mutation state so the row reflects user intent immediately.
          const inFlight: { dot: string; label: string } | null =
            pendingConnectId === s.id
              ? { dot: "#facc15", label: "连接中" }
              : pendingDisconnectId === s.id
                ? { dot: "#facc15", label: "断开中" }
                : null;
          const info = inFlight ?? statusInfo(s.runtime_status, s.enabled);
          const isRunning = s.runtime_status === "connected";
          const connectionParam = s.transport === "stdio" ? (s.command ?? "—") : "—";
          return (
            <div
              key={s.id}
              className={`group grid ${GRID} items-center gap-2 px-5 py-3 transition-colors hover:bg-zinc-50`}
              style={{ borderTop: "1px solid var(--color-border-soft)" }}
            >
              <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: info.dot }} />
              <span className="truncate text-sm" style={{ color: "var(--color-ink-soft)" }}>{s.name}</span>
              <span className="truncate text-xs" style={{ color: "var(--color-ink-faint)" }}>{s.transport}</span>
              <span className="truncate font-mono text-xs" style={{ color: "var(--color-ink-faint)" }}>{connectionParam}</span>
              <span className="truncate text-xs" style={{ color: "var(--color-ink-faint)" }}>
                {s.url || (s.host ?? "localhost")}
              </span>
              <span className="truncate text-xs tabular-nums" style={{ color: "var(--color-ink-faint)" }}>
                {s.port ?? "—"}
              </span>
              <span className="text-xs" style={{ color: "var(--color-ink-faint)" }}>{info.label}</span>
              <RowActionsMenu
                actions={[
                  isRunning
                    ? { label: "停止", onClick: () => disconnectMut.mutate(s.id) }
                    : { label: "启用", onClick: () => connectMut.mutate(s.id) },
                  { label: "编辑", onClick: () => onEdit(s as unknown as Record<string, unknown>) },
                  {
                    label: "删除",
                    tone: "danger",
                    onClick: () => {
                      if (confirm(`删除 MCP "${s.name}"？`)) deleteMut.mutate(s.id);
                    },
                  },
                ]}
              />
            </div>
          );
        })
      )}
    </div>
  );
}

export default McpTable;
