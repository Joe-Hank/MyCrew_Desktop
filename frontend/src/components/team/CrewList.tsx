import { useCrews, useDeleteCrew, type Crew } from "../../queries/useTeamQuery";

function CrewList({
  onEdit,
  onNew,
}: {
  onEdit: (crew: Crew) => void;
  onNew: () => void;
}) {
  const { data: crews, isLoading } = useCrews();
  const deleteMut = useDeleteCrew();

  if (isLoading) {
    return <div className="p-4 text-xs text-zinc-400">加载中...</div>;
  }

  const items = crews ?? [];

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-zinc-500">
          Crews ({items.length})
        </h3>
        <button
          onClick={onNew}
          className="rounded bg-blue-500 px-3 py-1 text-[11px] font-medium text-white hover:bg-blue-600"
        >
          + 新建 Crew
        </button>
      </div>

      {items.length === 0 && (
        <p className="py-8 text-center text-xs text-zinc-400">暂无 Crew，点击上方按钮创建</p>
      )}

      {items.map((crew) => (
        <div
          key={crew.id}
          className="flex cursor-pointer items-start justify-between rounded-lg border border-zinc-200 p-3 transition-colors hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800/50"
          onClick={() => onEdit(crew)}
        >
          <div className="flex-1">
            <div className="mb-1 flex items-center gap-2">
              <span className="text-sm font-medium">{crew.name}</span>
              {crew.is_auto_generated && (
                <span className="rounded bg-purple-100 px-1 py-0.5 text-[9px] text-purple-600 dark:bg-purple-900 dark:text-purple-300">
                  自动生成
                </span>
              )}
            </div>
            <div className="flex gap-1.5 text-[10px] text-zinc-400">
              <span className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
                {crew.process === "sequential" ? "顺序" : "层级"}
              </span>
              <span className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">
                成员×{crew.agent_ids.length}
              </span>
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (confirm(`删除 Crew "${crew.name}"？`)) deleteMut.mutate(crew.id);
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

export default CrewList;
