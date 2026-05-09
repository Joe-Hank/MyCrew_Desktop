import { useTools, useDeleteTool, useScanTools, type Tool } from "../../queries/useTeamQuery";

function ToolList({ onNew }: { onNew: () => void }) {
  const { data: tools, isLoading } = useTools();
  const deleteMut = useDeleteTool();
  const scanMut = useScanTools();

  if (isLoading) {
    return <div className="p-4 text-xs text-zinc-400">加载中...</div>;
  }

  const items = tools ?? [];
  const builtinTools = items.filter((t) => t.source === "builtin");
  const userTools = items.filter((t) => t.source !== "builtin");

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-zinc-500">
          Tools ({items.length})
        </h3>
        <div className="flex gap-2">
          <button
            onClick={() => scanMut.mutate()}
            disabled={scanMut.isPending}
            className="rounded border border-zinc-300 px-2 py-1 text-[11px] transition-colors hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800"
          >
            {scanMut.isPending ? "扫描中..." : "扫描 src/tools"}
          </button>
          <button
            onClick={onNew}
            className="rounded bg-blue-500 px-3 py-1 text-[11px] font-medium text-white hover:bg-blue-600"
          >
            + 新建 Tool
          </button>
        </div>
      </div>

      {items.length === 0 && (
        <p className="py-8 text-center text-xs text-zinc-400">暂无 Tool，点击扫描或手动创建</p>
      )}

      {/* Builtin tools */}
      {builtinTools.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
            内置 ({builtinTools.length})
          </h4>
          <div className="space-y-1.5">
            {builtinTools.map((tool) => (
              <ToolItem key={tool.id} tool={tool} onDelete={() => deleteMut.mutate(tool.id)} />
            ))}
          </div>
        </div>
      )}

      {/* User tools */}
      {userTools.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
            用户 ({userTools.length})
          </h4>
          <div className="space-y-1.5">
            {userTools.map((tool) => (
              <ToolItem key={tool.id} tool={tool} onDelete={() => deleteMut.mutate(tool.id)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ToolItem({ tool, onDelete }: { tool: Tool; onDelete: () => void }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-zinc-200 px-3 py-2 dark:border-zinc-700">
      <div className="flex items-center gap-2">
        <span className={`rounded px-1 py-0.5 text-[9px] font-medium ${
          tool.source === "builtin"
            ? "bg-green-100 text-green-600 dark:bg-green-900 dark:text-green-300"
            : "bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-300"
        }`}>
          {tool.source === "builtin" ? "内置" : "用户"}
        </span>
        <span className="text-xs font-medium">{tool.name}</span>
        {tool.script_path && (
          <span className="max-w-[200px] truncate text-[10px] text-zinc-400" title={tool.script_path}>
            {tool.script_path}
          </span>
        )}
      </div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          if (confirm(`删除 Tool "${tool.name}"？`)) onDelete();
        }}
        className="text-zinc-300 hover:text-red-500"
      >
        ×
      </button>
    </div>
  );
}

export default ToolList;
