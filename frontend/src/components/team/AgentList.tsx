import { useAgents, useDeleteAgent, type Agent } from "../../queries/useTeamQuery";

function AgentList({
  onEdit,
  onNew,
}: {
  onEdit: (agent: Agent) => void;
  onNew: () => void;
}) {
  const { data: agents, isLoading } = useAgents();
  const deleteMut = useDeleteAgent();

  if (isLoading) {
    return <div className="p-4 text-xs text-zinc-400">加载中...</div>;
  }

  const items = agents ?? [];

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-zinc-500">
          Agents ({items.length})
        </h3>
        <button
          onClick={onNew}
          className="rounded bg-blue-500 px-3 py-1 text-[11px] font-medium text-white hover:bg-blue-600"
        >
          + 新建 Agent
        </button>
      </div>

      {items.length === 0 && (
        <p className="py-8 text-center text-xs text-zinc-400">暂无 Agent，点击上方按钮创建</p>
      )}

      {items.map((agent) => (
        <div
          key={agent.id}
          className="flex cursor-pointer items-start justify-between rounded-lg border border-zinc-200 p-3 transition-colors hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800/50"
          onClick={() => onEdit(agent)}
        >
          <div className="flex-1">
            <div className="mb-1 flex items-center gap-2">
              <span className="text-sm font-medium">{agent.role}</span>
              {agent.is_auto_generated && (
                <span className="rounded bg-purple-100 px-1 py-0.5 text-[9px] text-purple-600 dark:bg-purple-900 dark:text-purple-300">
                  自动生成
                </span>
              )}
            </div>
            {agent.goal && (
              <p className="mb-1 line-clamp-1 text-[11px] text-zinc-500">{agent.goal}</p>
            )}
            <div className="flex flex-wrap gap-1.5 text-[10px] text-zinc-400">
              {agent.reasoning && <span className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">推理</span>}
              {agent.memory_enabled && <span className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">记忆</span>}
              {agent.thinking_mode && <span className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">思考</span>}
              <span className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
                重试×{agent.max_retry}
              </span>
              <span className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
                工具×{agent.tool_ids.length}
              </span>
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (confirm(`删除 Agent "${agent.role}"？`)) deleteMut.mutate(agent.id);
            }}
            className="shrink-0 text-zinc-300 hover:text-red-500"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

export default AgentList;
