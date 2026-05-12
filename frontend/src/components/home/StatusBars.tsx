import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useMcpStatus,
  useConnectMcpServer,
  useDisconnectMcpServer,
  type McpServerStatus,
} from "../../queries/useMcpQuery";
import {
  useLlmQuota,
  useRefreshLlmQuota,
  type ProviderQuota,
} from "../../queries/useLlmQuery";
import { useEvent } from "../../hooks/useEvent";

const statusDotColor: Record<string, string> = {
  connected: "#10b981",
  connecting: "#facc15",
  error: "#ef4444",
  disconnected: "#cbd5e1",
};

const statusLabels: Record<string, string> = {
  connected: "在线",
  connecting: "连接中",
  error: "错误",
  disconnected: "离线",
};

function ServerChip({ server }: { server: McpServerStatus }) {
  const connect = useConnectMcpServer();
  const disconnect = useDisconnectMcpServer();
  const isOnline = server.status === "connected";
  const isPending = connect.isPending || disconnect.isPending;

  function handleClick() {
    if (isPending) return;
    if (isOnline) {
      disconnect.mutate(server.server_id);
    } else {
      connect.mutate(server.server_id);
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={isPending}
      title={
        server.error
          ? `${server.name}: ${server.error}`
          : `${server.name} (${statusLabels[server.status] ?? server.status}) — ${server.tools_count} tools`
      }
      className="flex shrink-0 items-center gap-1.5 rounded-full bg-white px-3 py-1 text-xs transition-opacity hover:opacity-80 disabled:opacity-50"
      style={{ color: "var(--color-ink-label)" }}
    >
      <span className="truncate max-w-[100px]">{server.name}</span>
      <span
        className="inline-block h-2 w-2 rounded-full"
        style={{ backgroundColor: statusDotColor[server.status] ?? "#cbd5e1" }}
      />
    </button>
  );
}

function McpRow() {
  const { data: status, isLoading } = useMcpStatus();
  const qc = useQueryClient();

  const handleStatusChange = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["mcp"] });
  }, [qc]);

  useEvent("mcp.status_changed", handleStatusChange);

  const servers = status?.servers ?? [];

  return (
    <div
      className="flex items-center gap-3 rounded-[16px] px-4 py-2.5"
      style={{ backgroundColor: "var(--color-surface-alt)" }}
    >
      <span
        className="shrink-0 text-sm font-medium"
        style={{ color: "var(--color-ink) " }}
      >
        MCP连接：
      </span>
      <div className="flex flex-1 items-center gap-2 overflow-x-auto">
        {isLoading ? (
          <span className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>
            加载中...
          </span>
        ) : servers.length === 0 ? (
          <span className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>
            未配置 MCP 服务器
          </span>
        ) : (
          servers.map((s) => <ServerChip key={s.server_id} server={s} />)
        )}
      </div>
      <button
        onClick={handleStatusChange}
        className="shrink-0 rounded-full bg-white px-4 py-1 text-xs transition-opacity hover:opacity-80"
        style={{ color: "var(--color-ink-label)" }}
      >
        刷新
      </button>
    </div>
  );
}

/** Three-mode chip per plan §11.2:
 *  - display="percent"      → integer percentage "{value}%"
 *  - display="tokens_m"     → integer M "{value}M"
 *  - display="available"    → green dot
 *  - display="unavailable"  → red dot
 */
function QuotaChip({ q }: { q: ProviderQuota }) {
  const tail = (() => {
    if (q.display === "percent" && q.value !== null) {
      return <span style={{ color: "var(--color-ink-faint)" }}>{q.value}%</span>;
    }
    if (q.display === "tokens_m" && q.value !== null) {
      return <span style={{ color: "var(--color-ink-faint)" }}>{q.value}M</span>;
    }
    return (
      <span
        className="inline-block h-2 w-2 rounded-full"
        style={{
          backgroundColor: q.display === "available" ? "#10b981" : "#ef4444",
        }}
      />
    );
  })();

  return (
    <div
      className="flex shrink-0 items-center gap-2 rounded-full bg-white px-3 py-1 text-xs"
      style={{ color: "var(--color-ink-label)" }}
      title={q.raw || `${q.name} (${q.display})`}
    >
      <span>{q.name}</span>
      {tail}
    </div>
  );
}

function TokenRow() {
  const { data: quotas = [], isLoading } = useLlmQuota();
  const refresh = useRefreshLlmQuota();
  const qc = useQueryClient();

  // WS push: backend broadcasts llm.quota_changed after every probe;
  // patch the cache so the row updates without waiting for the next 30s tick.
  const handleQuotaChange = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      const providers = msg.payload.providers as ProviderQuota[] | undefined;
      if (Array.isArray(providers)) {
        qc.setQueryData(["llm", "quota"], providers);
      }
    },
    [qc],
  );
  useEvent("llm.quota_changed", handleQuotaChange);

  return (
    <div
      className="flex items-center gap-3 rounded-[16px] px-4 py-2.5"
      style={{ backgroundColor: "var(--color-surface-alt)" }}
    >
      <span
        className="shrink-0 text-sm font-medium"
        style={{ color: "var(--color-ink)" }}
      >
        Tokens：
      </span>
      <div className="flex flex-1 items-center gap-2 overflow-x-auto">
        {isLoading ? (
          <span className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>
            加载中...
          </span>
        ) : quotas.length === 0 ? (
          <span className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>
            未配置 LLM
          </span>
        ) : (
          quotas.map((q) => <QuotaChip key={q.provider_id} q={q} />)
        )}
      </div>
      <button
        onClick={() => refresh.mutate()}
        disabled={refresh.isPending}
        className="shrink-0 rounded-full bg-white px-4 py-1 text-xs transition-opacity hover:opacity-80 disabled:opacity-50"
        style={{ color: "var(--color-ink-label)" }}
      >
        {refresh.isPending ? "..." : "刷新"}
      </button>
    </div>
  );
}

function StatusBars() {
  return (
    <div className="space-y-2">
      <McpRow />
      <TokenRow />
    </div>
  );
}

export default StatusBars;
