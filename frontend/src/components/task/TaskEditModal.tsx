import { useState } from "react";
import type { Task } from "../../queries/useProjectQuery";
import { useUpdateTask } from "../../queries/useWorkflowQuery";
import { useAssignableAgents } from "../../queries/useAgentQuery";

// The globals.css `:root.dark` block intentionally INVERTS Tailwind's
// `bg-zinc-*` scale (zinc-900 → light grey in dark mode, zinc-100 → dark
// grey). That makes the usual `bg-white dark:bg-zinc-900` pattern produce
// LIGHT modals in dark mode and (via Tailwind v4's missing-var fallback
// to transparent) DARK modals in light mode — exactly the inversion the
// user reported. Everything here uses theme-aware CSS variables
// (--color-card / --color-card-alt / etc.) which are defined in BOTH
// @theme and :root.dark, so they switch correctly in both modes.
const BG_CARD = "var(--color-card)";
const BG_CARD_ALT = "var(--color-card-alt)";
const BORDER_SOFT = "1px solid var(--color-border-soft)";
const TEXT_INK = "var(--color-ink)";
const TEXT_INK_SOFT = "var(--color-ink-soft)";
const TEXT_INK_FAINT = "var(--color-ink-faint)";

function TaskEditModal({
  task,
  onClose,
}: {
  task: Task;
  onClose: () => void;
}) {
  const { data: agents } = useAssignableAgents();
  const update = useUpdateTask();

  const [title, setTitle] = useState(task.title);
  const [detail, setDetail] = useState(task.detail);
  const [agentId, setAgentId] = useState<string>(task.agent_id ?? "");

  // 上游依赖（deps）不再在这里编辑 —— 用户在画布上拖线/右键删边
  // 来管理拓扑关系，避免两套编辑入口语义打架。

  async function handleSave() {
    const patch: {
      title?: string;
      detail?: string;
      agent_id?: string | null;
    } = {};
    if (title !== task.title) patch.title = title;
    if (detail !== task.detail) patch.detail = detail;
    if ((agentId || null) !== (task.agent_id ?? null)) {
      patch.agent_id = agentId || null;
    }
    if (Object.keys(patch).length === 0) {
      onClose();
      return;
    }
    await update.mutateAsync({ taskId: task.id, ...patch });
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.4)" }}
    >
      <div
        className="flex max-h-[88vh] w-full max-w-lg flex-col rounded-lg shadow-xl"
        style={{ backgroundColor: BG_CARD, border: BORDER_SOFT, color: TEXT_INK }}
      >
        <div className="px-5 py-3" style={{ borderBottom: BORDER_SOFT }}>
          <h3 className="text-sm font-semibold" style={{ color: TEXT_INK_SOFT }}>
            编辑任务
          </h3>
        </div>

        <div className="space-y-4 overflow-y-auto px-5 py-4">
          {/* Title */}
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: TEXT_INK_FAINT }}>
              标题
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full rounded px-3 py-1.5 text-sm outline-none"
              style={{
                backgroundColor: BG_CARD_ALT,
                border: BORDER_SOFT,
                color: TEXT_INK,
              }}
            />
          </div>

          {/* Detail */}
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: TEXT_INK_FAINT }}>
              详情
            </label>
            <textarea
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
              rows={4}
              className="w-full resize-none rounded px-3 py-1.5 text-sm outline-none"
              style={{
                backgroundColor: BG_CARD_ALT,
                border: BORDER_SOFT,
                color: TEXT_INK,
              }}
            />
          </div>

          {/* Agent picker */}
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: TEXT_INK_FAINT }}>
              执行 Agent
            </label>
            <select
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              className="w-full rounded px-3 py-1.5 text-sm outline-none"
              style={{
                backgroundColor: BG_CARD_ALT,
                border: BORDER_SOFT,
                color: TEXT_INK,
              }}
            >
              <option value="">
                {task.kind === "final_qa" ? "（默认 QA-Agent）" : "（待指定）"}
              </option>
              {(agents ?? []).map((a) => (
                <option key={a.id} value={a.id}>{a.role}</option>
              ))}
            </select>
          </div>

        </div>

        <div className="flex justify-end gap-2 px-5 py-3" style={{ borderTop: BORDER_SOFT }}>
          <button
            onClick={onClose}
            className="rounded px-3 py-1.5 text-xs"
            style={{
              backgroundColor: BG_CARD_ALT,
              border: BORDER_SOFT,
              color: TEXT_INK_SOFT,
            }}
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={update.isPending || !title.trim()}
            className="rounded px-4 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
            style={{ backgroundColor: "var(--color-brand-500)" }}
          >
            {update.isPending ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default TaskEditModal;
