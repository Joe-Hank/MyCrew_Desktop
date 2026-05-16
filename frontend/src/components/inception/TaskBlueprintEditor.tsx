import { useState } from "react";
import type { Blueprint } from "../../queries/useInceptionQuery";
import { useAssignableAgents } from "../../queries/useAgentQuery";
import { useCrews } from "../../queries/useTeamQuery";

interface Props {
  blueprint: Blueprint;
  onChange: (bp: Blueprint) => void;
  onReEvaluate: () => void;
  reEvaluating: boolean;
}

type BpTask = Blueprint["tasks"][number];

function TaskBlueprintEditor({
  blueprint,
  onChange,
  onReEvaluate,
  reEvaluating,
}: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const { data: agents } = useAssignableAgents();
  const agentList = agents ?? [];
  // PM v4: tasks may be assigned to a Crew instead of a single agent.
  // We need the crew list to render the human-readable label.
  const { data: crews } = useCrews();
  const crewList = crews ?? [];

  function updateTask(index: number, patch: Partial<BpTask>) {
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

  // PM v4: prefer performer_kind/performer_id when set (filled by
  // planner_orchestrator._assemble_draft_blueprint). Fall back to
  // legacy agent_id for PM v3 / iterate / setup tasks.
  function performerLabel(task: BpTask): string {
    const kind = task.performer_kind;
    const pid = task.performer_id ?? task.agent_id;
    if (kind === "crew") {
      if (!pid) return "Crew: 待指定";
      const c = crewList.find((x) => x.id === pid);
      return c ? `Crew: ${c.name}` : "Crew: 未知";
    }
    // kind === "agent" or undefined (legacy)
    if (!pid) return task.kind === "final_qa" ? "QA-Agent" : "待指定";
    const a = agentList.find((x) => x.id === pid);
    return a?.role ?? "未知 Agent";
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
                <div className="flex items-center gap-2 text-xs">
                  <label style={{ color: "var(--color-ink-faint)" }}>执行者:</label>
                  <select
                    // Stored as "agent:<id>" / "crew:<id>" so we can
                    // recover the kind on change; mirrors what
                    // planner_orchestrator persists into the task row.
                    value={
                      task.performer_kind && (task.performer_id ?? task.agent_id)
                        ? `${task.performer_kind}:${task.performer_id ?? task.agent_id}`
                        : task.agent_id
                          ? `agent:${task.agent_id}`
                          : ""
                    }
                    onChange={(e) => {
                      const v = e.target.value;
                      if (!v) {
                        updateTask(i, {
                          agent_id: null,
                          performer_kind: null,
                          performer_id: null,
                        });
                        return;
                      }
                      const [kind, id] = v.split(":", 2);
                      if (kind === "crew") {
                        updateTask(i, {
                          performer_kind: "crew",
                          performer_id: id,
                          agent_id: null,
                        });
                      } else {
                        updateTask(i, {
                          performer_kind: "agent",
                          performer_id: id,
                          agent_id: id,
                        });
                      }
                    }}
                    className="flex-1 rounded-md bg-zinc-50 px-2 py-1 text-xs outline-none"
                  >
                    <option value="">
                      {task.kind === "final_qa" ? "（默认 QA-Agent）" : "（待指定）"}
                    </option>
                    {crewList.length > 0 && (
                      <optgroup label="Crew（多 Agent 协作）">
                        {crewList.map((c) => (
                          <option key={`crew:${c.id}`} value={`crew:${c.id}`}>
                            {c.name}
                          </option>
                        ))}
                      </optgroup>
                    )}
                    <optgroup label="单 Agent">
                      {agentList.map((a) => (
                        <option key={`agent:${a.id}`} value={`agent:${a.id}`}>
                          {a.role}
                        </option>
                      ))}
                    </optgroup>
                  </select>
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
                    {task.kind === "setup" && (
                      <span
                        className="rounded px-1.5 py-0.5 text-[10px]"
                        style={{ backgroundColor: "rgba(12, 140, 233, 0.14)", color: "var(--color-brand-500)" }}
                        title="项目初始化任务"
                      >
                        初始化
                      </span>
                    )}
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
                    {performerLabel(task)}
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
