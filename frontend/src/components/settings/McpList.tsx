import { useMcpServers } from "../../queries/useMcpQuery";

function McpList({ onSelect }: { onSelect: (id: string) => void }) {
  const { data: servers = [], isLoading } = useMcpServers();

  if (isLoading) return <div className="p-4 text-zinc-400">加载中...</div>;

  if (servers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-12 text-zinc-400">
        <span className="text-3xl">🔌</span>
        <p className="text-sm">暂无 MCP 服务器</p>
        <p className="text-xs">点击右上角"+ 新建"添加 MCP 服务器</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
      {(servers as Record<string, unknown>[]).map((s) => (
        <button
          key={s.id as string}
          onClick={() => onSelect(s.id as string)}
          className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{s.name as string}</span>
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800">
                {s.transport as string}
              </span>
              {!s.enabled && (
                <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] text-zinc-400 dark:bg-zinc-700">
                  已禁用
                </span>
              )}
            </div>
            <div className="mt-0.5 text-[11px] text-zinc-400">
              {s.transport === "stdio"
                ? (s.command as string) || "未配置命令"
                : (s.url as string) || "未配置 URL"}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                s.enabled ? "bg-green-500" : "bg-zinc-400"
              }`}
            />
            <span className="text-zinc-300 dark:text-zinc-600">›</span>
          </div>
        </button>
      ))}
    </div>
  );
}

export default McpList;
