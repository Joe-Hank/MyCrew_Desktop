import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useMcpStatus,
  useConnectMcpServer,
  useDisconnectMcpServer,
  type McpServerStatus,
} from "../../queries/useMcpQuery";
import { useEvent } from "../../hooks/useEvent";

const statusColors: Record<string, string> = {
  connected: "bg-green-500",
  connecting: "bg-yellow-500 animate-pulse",
  error: "bg-red-500",
  disconnected: "bg-zinc-400",
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
      className="flex shrink-0 items-center gap-1.5 rounded-full border border-zinc-200 px-2.5 py-1 text-xs transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
    >
      <span
        className={`inline-block h-2 w-2 rounded-full ${statusColors[server.status] ?? "bg-zinc-400"}`}
      />
      <span className="max-w-[120px] truncate">{server.name}</span>
      {isOnline && (
        <span className="text-zinc-400">{server.tools_count}</span>
      )}
    </button>
  );
}

function McpStatusBar() {
  const { data: status, isLoading } = useMcpStatus();
  const qc = useQueryClient();

  const handleStatusChange = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["mcp"] });
  }, [qc]);

  useEvent("mcp.status_changed", handleStatusChange);

  if (isLoading) {
    return (
      <div className="flex h-10 items-center px-4 text-xs text-zinc-400">
        MCP 加载中...
      </div>
    );
  }

  const servers = status?.servers ?? [];

  if (servers.length === 0) {
    return (
      <div className="flex h-10 items-center px-4 text-xs text-zinc-400">
        未配置 MCP 服务器 — 前往设置页添加
      </div>
    );
  }

  return (
    <div className="flex h-10 items-center gap-2 overflow-x-auto px-4">
      <span className="shrink-0 text-xs font-medium text-zinc-500">MCP</span>
      <span className="shrink-0 text-xs text-zinc-400">
        {status?.online ?? 0}/{servers.length}
      </span>
      <div className="mx-1 h-4 w-px bg-zinc-200 dark:bg-zinc-700" />
      {servers.map((s) => (
        <ServerChip key={s.server_id} server={s} />
      ))}
    </div>
  );
}

export default McpStatusBar;
