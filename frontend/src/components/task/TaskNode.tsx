import { useState, useRef, useEffect } from "react";
import type { Task } from "../../queries/useProjectQuery";

export type TaskAction =
  | { kind: "edit"; task: Task }
  | { kind: "pause"; task: Task }
  | { kind: "retry"; task: Task }
  | { kind: "agent_chat"; task: Task }
  | { kind: "view_io"; task: Task; direction: "in" | "out" };

const STATUS_STYLES: Record<string, { dot: string; bg: string; label: string }> = {
  pending: { dot: "bg-zinc-400", bg: "border-zinc-300 dark:border-zinc-600", label: "待执行" },
  running: { dot: "bg-blue-500 animate-pulse", bg: "border-blue-400 dark:border-blue-600", label: "运行中" },
  paused: { dot: "bg-yellow-500", bg: "border-yellow-400 dark:border-yellow-600", label: "已暂停" },
  done: { dot: "bg-green-500", bg: "border-green-400 dark:border-green-600", label: "已完成" },
  failed: { dot: "bg-red-500", bg: "border-red-400 dark:border-red-600", label: "失败" },
  aborted: { dot: "bg-red-400", bg: "border-red-300 dark:border-red-700", label: "已中止" },
  validation_failed: { dot: "bg-orange-500", bg: "border-orange-400 dark:border-orange-600", label: "验证失败" },
  blocked: { dot: "bg-zinc-500", bg: "border-zinc-400 dark:border-zinc-600", label: "阻塞" },
};

function TaskNode({
  task,
  projectRunning,
  onAction,
}: {
  task: Task;
  projectRunning: boolean;
  onAction: (action: TaskAction) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const style = (STATUS_STYLES[task.status] ?? STATUS_STYLES.pending) as { dot: string; bg: string; label: string };

  useEffect(() => {
    if (!menuOpen) return;
    function close(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  const canEdit = !projectRunning && task.status !== "running";
  const canPause = task.status === "running";
  const canRetry = ["done", "failed", "validation_failed", "aborted"].includes(task.status) && !projectRunning;
  const canChat = ["failed", "validation_failed", "blocked"].includes(task.status);

  return (
    <div className={`relative w-52 rounded-lg border-2 bg-white p-3 shadow-sm dark:bg-zinc-900 ${style.bg}`}>
      {/* Status dot + title */}
      <div className="mb-1.5 flex items-start justify-between">
        <div className="flex items-center gap-1.5">
          <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${style.dot}`} />
          <span className="text-xs font-medium leading-tight">{task.title}</span>
        </div>
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          className="shrink-0 rounded p-0.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800"
        >
          <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="currentColor">
            <circle cx="8" cy="3" r="1.5" />
            <circle cx="8" cy="8" r="1.5" />
            <circle cx="8" cy="13" r="1.5" />
          </svg>
        </button>
      </div>

      {/* Detail preview */}
      {task.detail && (
        <p className="mb-1.5 line-clamp-2 text-[10px] leading-snug text-zinc-500">
          {task.detail}
        </p>
      )}

      {/* Agent + status label */}
      <div className="flex items-center justify-between">
        <span className="truncate text-[10px] text-zinc-400">
          {task.agent_id ? `Agent: ${task.agent_id.slice(-6)}` : "未指定 Agent"}
        </span>
        <span className="text-[9px] font-medium text-zinc-500">{style.label}</span>
      </div>

      {/* Operations menu */}
      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-0 top-8 z-20 w-36 rounded-md border border-zinc-200 bg-white py-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
        >
          <MenuItem
            label="编辑详情"
            disabled={!canEdit}
            onClick={() => { onAction({ kind: "edit", task }); setMenuOpen(false); }}
          />
          {canPause && (
            <MenuItem
              label="暂停任务"
              onClick={() => { onAction({ kind: "pause", task }); setMenuOpen(false); }}
            />
          )}
          <MenuItem
            label="重新执行"
            disabled={!canRetry}
            onClick={() => { onAction({ kind: "retry", task }); setMenuOpen(false); }}
          />
          <MenuItem
            label="Agent 对话"
            disabled={!canChat}
            onClick={() => { onAction({ kind: "agent_chat", task }); setMenuOpen(false); }}
          />
          <div className="my-1 border-t border-zinc-100 dark:border-zinc-800" />
          <MenuItem
            label="查看输入"
            onClick={() => { onAction({ kind: "view_io", task, direction: "in" }); setMenuOpen(false); }}
          />
          <MenuItem
            label="查看输出"
            onClick={() => { onAction({ kind: "view_io", task, direction: "out" }); setMenuOpen(false); }}
          />
        </div>
      )}
    </div>
  );
}

function MenuItem({ label, disabled, onClick }: { label: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex w-full px-3 py-1.5 text-left text-[11px] hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-zinc-800"
    >
      {label}
    </button>
  );
}

export default TaskNode;
