import { useMcpServers } from "../../queries/useMcpQuery";

const COLUMNS = ["名称", "传输协议", "连接参数", "主机", "端口", "状态", "操作"] as const;

function McpTable({ onEdit }: { onEdit: (s: Record<string, unknown>) => void }) {
  const { data: servers = [], isLoading } = useMcpServers();

  if (isLoading) return <div className="py-8 text-center text-sm text-zinc-400">加载中...</div>;

  if (servers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-zinc-400">
        <span className="text-3xl">🔌</span>
        <p className="text-sm">暂无 MCP 服务器</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <div className="grid grid-cols-[1.2fr_1fr_1.2fr_1fr_0.6fr_0.8fr_auto] gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        {COLUMNS.map((col) => (
          <span key={col} className="text-xs font-medium text-zinc-400">{col}</span>
        ))}
      </div>

      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {(servers as Record<string, unknown>[]).map((s) => (
          <div
            key={s.id as string}
            className="group grid grid-cols-[1.2fr_1fr_1.2fr_1fr_0.6fr_0.8fr_auto] items-center gap-2 px-4 py-3 transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
          >
            <div className="flex items-center gap-2">
              <span className={`inline-block h-2.5 w-2.5 rounded-full ${s.enabled ? "bg-green-500" : "bg-zinc-400"}`} />
              <span className="text-sm font-medium">{s.name as string}</span>
            </div>
            <span className="text-xs text-zinc-600 dark:text-zinc-400">{s.transport as string}</span>
            <span className="truncate text-xs text-zinc-600 dark:text-zinc-400">
              {"*".repeat(11)}
            </span>
            <span className="text-xs text-zinc-600 dark:text-zinc-400">
              {(s.host as string) || "localhost"}
            </span>
            <span className="text-xs text-zinc-600 dark:text-zinc-400">
              {(s.port as string) || "—"}
            </span>
            <span className={`text-xs ${s.enabled ? "text-green-600" : "text-zinc-400"}`}>
              {s.enabled ? "运行中" : "已禁用"}
            </span>
            <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <button
                onClick={() => onEdit(s)}
                className="rounded-2xl border border-zinc-200 bg-white px-3 py-1 text-xs text-zinc-600 shadow-sm hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
              >
                编辑
              </button>
              <button
                className="rounded-2xl border border-zinc-200 bg-white px-3 py-1 text-xs text-zinc-600 shadow-sm hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
              >
                启用
              </button>
              <button
                className="rounded-2xl bg-red-400 px-3 py-1 text-xs text-white shadow-sm hover:bg-red-500"
              >
                删除
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default McpTable;
