import { useState } from "react";
import type { Blueprint } from "../../queries/useInceptionQuery";

interface Props {
  blueprint: Blueprint;
  onChange: (bp: Blueprint) => void;
  onReEvaluate: () => void;
  reEvaluating: boolean;
}

function TaskBlueprintEditor({
  blueprint,
  onChange,
  onReEvaluate,
  reEvaluating,
}: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);

  function updateTask(index: number, patch: Partial<Blueprint["tasks"][0]>) {
    const tasks = blueprint.tasks.map((t, i) => (i === index ? { ...t, ...patch } : t));
    onChange({ ...blueprint, tasks });
  }

  function removeTask(index: number) {
    const tasks = blueprint.tasks.filter((_, i) => i !== index);
    const updated = tasks.map((t) => ({
      ...t,
      deps: t.deps.filter((d) => d !== index).map((d) => (d > index ? d - 1 : d)),
    }));
    onChange({ ...blueprint, tasks: updated });
    setEditingIndex(null);
  }

  function addTask() {
    const tasks = [
      ...blueprint.tasks,
      { title: "新任务", detail: "", deps: [], output_schema: {}, kind: "regular" as const },
    ];
    onChange({ ...blueprint, tasks });
    setEditingIndex(tasks.length - 1);
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold" style={{ color: "var(--color-ink-strong)" }}>
            任务蓝图
          </h3>
          <span
            className="rounded px-2 py-0.5 text-[10px]"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-faint)",
            }}
          >
            {blueprint.execution_kind}
          </span>
        </div>
        <button
          onClick={onReEvaluate}
          disabled={reEvaluating}
          className="rounded-lg border bg-white px-3 py-1 text-xs transition-colors hover:bg-zinc-50 disabled:opacity-50"
          style={{ borderColor: "var(--color-border-soft)", color: "var(--color-ink-label)" }}
        >
          {reEvaluating ? "评估中..." : "AI 复核"}
        </button>
      </div>

      <div className="flex-1 space-y-3 overflow-auto pr-1">
        {blueprint.tasks.map((task, i) => (
          <div
            key={i}
            className="rounded-lg bg-white p-3"
            style={{ border: "1px solid var(--color-border-soft)" }}
          >
            {editingIndex === i ? (
              <div className="space-y-2">
                <input
                  value={task.title}
                  onChange={(e) => updateTask(i, { title: e.target.value })}
                  className="w-full rounded-md bg-zinc-50 px-2 py-1.5 text-sm outline-none"
                  placeholder="任务标题"
                />
                <textarea
                  value={task.detail}
                  onChange={(e) => updateTask(i, { detail: e.target.value })}
                  rows={3}
                  className="w-full resize-none rounded-md bg-zinc-50 px-2 py-1.5 text-xs outline-none"
                  placeholder="详细描述"
                />
                <div className="flex items-center gap-2 text-xs">
                  <label style={{ color: "var(--color-ink-faint)" }}>依赖任务序号:</label>
                  <input
                    value={task.deps.map((d) => d + 1).join(",")}
                    onChange={(e) => {
                      const deps = e.target.value
                        .split(",")
                        .map((s) => parseInt(s.trim(), 10) - 1)
                        .filter((n) => !isNaN(n) && n >= 0 && n < blueprint.tasks.length && n !== i);
                      updateTask(i, { deps });
                    }}
                    className="flex-1 rounded-md bg-zinc-50 px-2 py-1 text-xs outline-none"
                    placeholder="如: 1,2"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setEditingIndex(null)}
                    className="rounded-md px-3 py-1 text-xs text-white"
                    style={{ backgroundColor: "var(--color-brand-500)" }}
                  >
                    完成
                  </button>
                  <button
                    onClick={() => removeTask(i)}
                    className="rounded-md border px-3 py-1 text-xs text-red-500"
                    style={{ borderColor: "var(--color-border-soft)" }}
                  >
                    删除
                  </button>
                </div>
              </div>
            ) : (
              <div className="cursor-pointer" onClick={() => setEditingIndex(i)} role="button" tabIndex={0}>
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold"
                      style={{ backgroundColor: "var(--color-surface-alt)", color: "var(--color-ink-muted)" }}
                    >
                      {i + 1}
                    </span>
                    <span className="text-sm font-medium" style={{ color: "var(--color-ink-soft)" }}>
                      Task{i + 1}. {task.title}
                    </span>
                    {task.kind === "final_qa" && (
                      <span
                        className="rounded px-1.5 py-0.5 text-[10px]"
                        style={{ backgroundColor: "rgba(245, 158, 11, 0.18)", color: "#92400e" }}
                      >
                        QA
                      </span>
                    )}
                  </div>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    style={{ color: "var(--color-ink-ghost)" }}>
                    <path d="M12 20h9" />
                    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
                  </svg>
                </div>
                {task.detail && (
                  <p
                    className="mb-2 line-clamp-2 text-xs"
                    style={{ color: "var(--color-ink-muted)" }}
                  >
                    {task.detail}
                  </p>
                )}
                <div className="flex items-center gap-3 text-[10px]" style={{ color: "var(--color-ink-faint)" }}>
                  <span className="flex items-center gap-1">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                      <circle cx="12" cy="7" r="4" />
                    </svg>
                    {task.kind === "final_qa" ? "QA-Agent" : "自动分配"}
                  </span>
                  {task.deps.length > 0 && (
                    <span>依赖: {task.deps.map((d) => `#${d + 1}`).join(", ")}</span>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}

        <button
          onClick={addTask}
          className="flex w-full items-center justify-center gap-1 rounded-lg border border-dashed py-2 text-xs transition-colors hover:bg-white/60"
          style={{ borderColor: "var(--color-border-strong)", color: "var(--color-ink-muted)" }}
        >
          + 添加任务
        </button>
      </div>
    </div>
  );
}

export default TaskBlueprintEditor;
