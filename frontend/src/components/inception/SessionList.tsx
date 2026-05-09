import { useInceptionSessions, type InceptionSession } from "../../queries/useInceptionQuery";

function SessionList({
  activeId,
  onSelect,
  onNew,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const { data: sessions, isLoading } = useInceptionSessions();

  if (isLoading) {
    return <div className="p-2 text-xs text-zinc-400">加载中...</div>;
  }

  const items = sessions ?? [];

  return (
    <div className="flex h-full flex-col">
      <button
        onClick={onNew}
        className="m-2 rounded border border-dashed border-zinc-300 py-1.5 text-xs text-zinc-500 transition-colors hover:border-blue-400 hover:text-blue-500 dark:border-zinc-600"
      >
        + 新建会话
      </button>

      <div className="flex-1 overflow-auto">
        {items.length === 0 && (
          <p className="p-2 text-center text-xs text-zinc-400">暂无会话</p>
        )}
        {items.map((s: InceptionSession) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`flex w-full flex-col items-start gap-0.5 border-b border-zinc-200 px-3 py-2 text-left transition-colors dark:border-zinc-700 ${
              activeId === s.id
                ? "bg-blue-50 dark:bg-blue-950"
                : "hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            <div className="flex w-full items-center justify-between">
              <span className="truncate text-xs font-medium">
                {s.project_name ?? `会话 ${s.id.slice(-6)}`}
              </span>
              {s.is_draft && (
                <span className="shrink-0 rounded bg-yellow-100 px-1 text-[9px] text-yellow-600 dark:bg-yellow-900 dark:text-yellow-300">
                  草稿
                </span>
              )}
            </div>
            <span className="text-[10px] text-zinc-400">
              {s.created_at?.substring(0, 16)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default SessionList;
