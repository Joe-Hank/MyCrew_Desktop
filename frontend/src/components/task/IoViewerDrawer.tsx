import { useState } from "react";
import type { Task } from "../../queries/useProjectQuery";
import { useTaskIO } from "../../queries/useWorkflowQuery";

function IoViewerDrawer({
  task,
  initialDirection,
  onClose,
}: {
  task: Task;
  initialDirection: "in" | "out";
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"in" | "out">(initialDirection);
  const { data: io, isLoading } = useTaskIO(task.id, tab);

  return (
    <div className="flex h-full flex-col border-l border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold">IO 查看器</span>
          <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800">
            {task.title}
          </span>
        </div>
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200">
          ✕
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-zinc-200 dark:border-zinc-700">
        <TabBtn label="输入" active={tab === "in"} onClick={() => setTab("in")} />
        <TabBtn label="输出" active={tab === "out"} onClick={() => setTab("out")} />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-3">
        {isLoading && (
          <div className="py-8 text-center text-xs text-zinc-400">加载中...</div>
        )}

        {!isLoading && !io?.structured && !io?.raw && (
          <div className="py-8 text-center text-xs text-zinc-400">
            暂无{tab === "in" ? "输入" : "输出"}数据
          </div>
        )}

        {!isLoading && io?.structured && (
          <div className="mb-3">
            <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
              结构化数据
            </h4>
            <pre className="rounded bg-zinc-50 p-3 text-[11px] leading-relaxed dark:bg-zinc-950">
              {JSON.stringify(io.structured, null, 2)}
            </pre>
          </div>
        )}

        {!isLoading && io?.raw && (
          <div>
            <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
              原始输出
            </h4>
            <pre className="whitespace-pre-wrap rounded bg-zinc-50 p-3 text-[11px] leading-relaxed dark:bg-zinc-950">
              {io.raw}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

function TabBtn({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-2 text-xs font-medium transition-colors ${
        active
          ? "border-b-2 border-blue-500 text-blue-600 dark:text-blue-400"
          : "text-zinc-400 hover:text-zinc-600"
      }`}
    >
      {label}
    </button>
  );
}

export default IoViewerDrawer;
