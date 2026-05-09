import { useMcpServers } from "../../queries/useMcpQuery";

function McpList({ onSelect }: { onSelect: (id: string) => void }) {
  const { data: servers = [], isLoading } = useMcpServers();

  if (isLoading) return <div className="p-4 text-zinc-400">加载中...</div>;

  if (servers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-8 text-zinc-400">
        <p>暂无 MCP 服务器</p>
        <p className="text-xs">点击左上角"新建"添加 MCP 服务器</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {(servers as Record<string, unknown>[]).map((s) => (
        <button
          key={s.id as string}
          onClick={() => onSelect(s.id as string)}
          className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
        >
          <div>
            <div className="text-sm font-medium">{s.name as string}</div>
            <div className="text-xs text-zinc-500">{s.transport as string}</div>
          </div>
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              s.enabled ? "bg-green-500" : "bg-zinc-400"
            }`}
          />
        </button>
      ))}
    </div>
  );
}

export default McpList;
