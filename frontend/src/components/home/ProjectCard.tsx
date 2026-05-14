import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  useProject,
  useDeleteProject,
  useCloneProject,
  useUpdateRootPath,
  useToggleFavorite,
  type Project,
  type Task,
} from "../../queries/useProjectQuery";
import { useCreateTask } from "../../queries/useWorkflowQuery";
import { useAgents } from "../../queries/useTeamQuery";
import { useCreateInceptionSession } from "../../queries/useInceptionQuery";
import { useInceptionStore } from "../../stores/useInceptionStore";
import { usePrefsStore } from "../../stores/usePrefsStore";

// ── Card state machine ─────────────────────────────────────────────
//
//   未定路径   → no root_path           → 任何按钮都不跳转，必须先配路径
//   待开始     → 路径已配 / 进度 = 0     → 「开始」跳转任务页
//   待继续     → 进度 > 0 / 非终态       → 「继续」跳转任务页
//   已完成     → state ∈ terminal set   → 「查看」跳转任务页
//
// Per PRD §2.3.6 — only the state-appropriate primary button navigates.
// Clicking the card body itself does NOT navigate (previously it did).
type CardState = "no_path" | "ready_to_start" | "ready_to_continue" | "completed";

const TERMINAL_STATES = new Set([
  "completed",
  "completed_with_warnings",
  "completed_with_issues",
  "aborted",
]);

function computeCardState(project: Project): CardState {
  if (!project.root_path) return "no_path";
  if (TERMINAL_STATES.has(project.state)) return "completed";
  if ((project.progress_pct ?? 0) > 0) return "ready_to_continue";
  if (project.state === "running" || project.state === "paused") {
    return "ready_to_continue";
  }
  return "ready_to_start";
}

const stateLabels: Record<string, string> = {
  ready: "未启动",
  running: "运行中",
  paused: "已暂停",
  stalled: "卡死(自动暂停)",
  completed: "已完成",
  completed_with_warnings: "完成(警告)",
  completed_with_issues: "完成(问题)",
  aborted: "已中止",
};

function ProjectCard({ project }: { project: Project }) {
  const navigate = useNavigate();
  const { data: detail } = useProject(project.id);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleteInput, setDeleteInput] = useState("");
  const [pathModal, setPathModal] = useState(false);
  const [pathInput, setPathInput] = useState(project.root_path ?? "");
  const deleteMut = useDeleteProject();
  const cloneMut = useCloneProject();
  const rootPathMut = useUpdateRootPath();
  const favMut = useToggleFavorite();
  const createSession = useCreateInceptionSession();
  const openDrawer = useInceptionStore((s) => s.openDrawer);
  const setActiveSession = useInceptionStore((s) => s.setActiveSession);
  const isFavorited = !!project.favorited_at;

  function handlePathSave() {
    if (!pathInput.trim()) return;
    rootPathMut.mutate({ id: project.id, root_path: pathInput.trim() });
    setPathModal(false);
  }

  function handleCopy() {
    if (cloneMut.isPending) return;
    cloneMut.mutate(project.id);
  }

  // Iteration — opens Plan Maker drawer in iterate mode. Only enabled
  // for completed* projects (per spec: "未完成的项目不可以迭代").
  // Creates a NEW project entry with parent_project_id pointing back to
  // this project; root_path + template + name(+iter suffix) are inherited
  // server-side by inception_svc.create_session(mode='iterate').
  const canIterate =
    TERMINAL_STATES.has(project.state) && !!project.root_path;
  async function handleIterate() {
    if (!canIterate) return;
    const llmId = usePrefsStore.getState().inceptionLlm ?? "";
    const modelId = usePrefsStore.getState().inceptionModel ?? "";
    if (!llmId) {
      alert("请先在设置 / Plan Maker 工具栏中选择 LLM。");
      return;
    }
    const fullLlmId = modelId ? `${llmId}:${modelId}` : llmId;
    const res = await createSession.mutateAsync({
      llm_id: fullLlmId,
      thinking_mode: usePrefsStore.getState().inceptionThinking,
      mode: "iterate",
      parent_project_id: project.id,
    });
    if (res.ok && res.data) {
      const id = (res.data as { id: string }).id;
      setActiveSession(id);
      openDrawer();
    }
  }

  const cardState = computeCardState(project);
  const progress = project.progress_pct ?? 0;
  const isRunning = project.state === "running";
  const isStalled = project.state === "stalled";
  // "Loaded" = user has opened this project's task page during the
  // current session. Persisted via usePrefsStore.lastProjectId.
  const lastProjectId = usePrefsStore((s) => s.lastProjectId);
  const isLoadedCompleted =
    TERMINAL_STATES.has(project.state) && lastProjectId === project.id;
  const tasks = detail?.tasks ?? [];

  // Halo rule table (matches plan §F):
  //   running  → blue pulsing wave   (still working)
  //   stalled  → red static glow     (watchdog detected hang)
  //   completed* + currently-loaded → blue static glow (cosmetic "open" marker)
  //   everything else → no halo (fixes the "ready_to_continue 也发光" bug)
  const haloShadow =
    isRunning
      ? undefined  // pulse via className keyframe, see below
      : isStalled
        ? "0 0 16px 3px rgba(239, 68, 68, 0.35)"
        : isLoadedCompleted
          ? "0 0 12px 2px rgba(12, 140, 233, 0.30)"
          : "0 1px 2px rgba(0,0,0,0.04)";
  const haloClassName = isRunning ? "card-halo-running" : "";

  const dateStr = project.created_at?.substring(0, 10) ?? "";

  function handlePrimaryClick() {
    // State-gated navigation: every state has exactly one button that
    // navigates, and it always goes to the same task page (the page itself
    // decides whether to show "start", "resume", or "view-only").
    if (cardState === "no_path") return;
    navigate(`/tasks/${project.id}`);
  }

  const primary: { label: string; disabled: boolean; tone: "primary" | "resume" | "view" | "locked" } = (() => {
    switch (cardState) {
      case "no_path":
        return { label: "请配置路径", disabled: true, tone: "locked" };
      case "ready_to_start":
        return { label: "开始", disabled: false, tone: "primary" };
      case "ready_to_continue":
        return { label: "继续", disabled: false, tone: "resume" };
      case "completed":
        return { label: "查看", disabled: false, tone: "view" };
    }
  })();

  const primaryBg = (() => {
    if (primary.disabled) return "var(--color-surface-alt)";
    if (primary.tone === "resume") return "#d39a3b";
    if (primary.tone === "view") return "var(--color-ink-muted)";
    return "var(--color-brand-500)";
  })();
  const primaryFg = primary.disabled ? "var(--color-ink-disabled)" : "white";

  function handleDelete() {
    if (deleteInput === project.name) {
      deleteMut.mutate({ id: project.id, name: project.name });
      setDeleteConfirm(false);
      setDeleteInput("");
    }
  }

  return (
    <div
      className={`group relative flex h-full flex-col rounded-[10px] bg-white p-4 ${haloClassName}`}
      style={{
        boxShadow: haloShadow,
        border: "1px solid var(--color-border-soft)",
      }}
    >
      {/* Header: title + 复制 + 删除 (per PRD §2.3.1-2.3.3) */}
      <div className="mb-1 flex items-start justify-between">
        <h3
          className="min-w-0 flex-1 truncate text-base font-semibold leading-tight"
          style={{ color: "var(--color-ink-muted)" }}
          title={project.name}
        >
          {project.name}
        </h3>
        <div className="ml-2 flex shrink-0 items-center gap-0.5">
          <button
            onClick={() => favMut.mutate({ id: project.id, favorited: !isFavorited })}
            disabled={favMut.isPending}
            className="rounded p-1 transition-colors hover:bg-zinc-100 disabled:opacity-50"
            title={isFavorited ? "已收藏 · 点击取消" : "收藏（置顶到第一页最左）"}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill={isFavorited ? "#facc15" : "none"}
              stroke={isFavorited ? "#facc15" : "currentColor"}
              strokeWidth="2"
              style={{ color: isFavorited ? undefined : "var(--color-ink-ghost)" }}
            >
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
          </button>
          <button
            onClick={handleCopy}
            disabled={cloneMut.isPending}
            className="rounded p-1 transition-colors hover:bg-zinc-100 disabled:opacity-50"
            title="复制项目（仅复制任务，不带路径/进度）"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              style={{ color: "var(--color-ink-ghost)" }}>
              <rect x="9" y="9" width="13" height="13" rx="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
          </button>
          <button
            onClick={() => setDeleteConfirm(true)}
            className="rounded p-1 transition-colors hover:bg-zinc-100"
            title="删除"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              style={{ color: "var(--color-ink-ghost)" }}>
              <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
            </svg>
          </button>
        </div>
      </div>

      {/* Meta: date + progress */}
      <div
        className="mb-2 flex items-center justify-between text-[11px]"
        style={{ color: "var(--color-ink-muted)" }}
      >
        <span>{dateStr}</span>
        <span>{Math.round(progress)}%</span>
      </div>

      {/* Progress bar */}
      <div
        className="mb-3 h-1.5 w-full overflow-hidden rounded-full"
        style={{ backgroundColor: "var(--color-surface-alt)" }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${progress}%`,
            backgroundColor: "var(--color-brand-500)",
          }}
        />
      </div>

      {/* Actions row: primary button + 路径 + 迭代 (placeholder) */}
      <div className="mb-3 flex items-center gap-2">
        <button
          onClick={handlePrimaryClick}
          disabled={primary.disabled}
          className="flex-1 rounded-lg py-2 text-sm font-medium transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-100"
          style={{ backgroundColor: primaryBg, color: primaryFg }}
          title={primary.disabled ? "请先配置项目根路径" : `跳转到任务页：${primary.label}`}
        >
          {primary.label}
        </button>

        <PathButton
          locked={!!project.root_path}
          configured={!!project.root_path}
          onClick={() => {
            setPathInput(project.root_path ?? "");
            setPathModal(true);
          }}
        />

        <button
          onClick={handleIterate}
          disabled={!canIterate}
          className="rounded-lg border bg-white px-3 py-2 text-sm transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50"
          style={{
            borderColor: "var(--color-border-soft)",
            color: canIterate ? "var(--color-ink-soft)" : "var(--color-ink-disabled)",
          }}
          title={
            canIterate
              ? "基于本项目开启新一轮迭代（继承根目录与模板）"
              : "仅已完成项目可迭代"
          }
        >
          迭代
        </button>
      </div>

      {/* State label */}
      <div
        className="mb-2 text-[10px] uppercase tracking-wide"
        style={{ color: "var(--color-ink-ghost)" }}
      >
        {stateLabels[project.state] ?? project.state}
      </div>

      {/* Task pills list — click any pill to expand its read-only detail.
          "+ 新建任务" is rendered at the bottom of the scroll area so a
          long list still leaves it discoverable. */}
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {tasks.length === 0 ? (
          <div
            className="rounded-lg py-3 text-center text-[11px]"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-ghost)",
            }}
          >
            无任务
          </div>
        ) : (
          tasks.map((task, idx) => <TaskPill key={task.id} task={task} index={idx} />)
        )}
        <NewTaskButton projectId={project.id} />
      </div>

      {/* Path config overlay */}
      {pathModal && (
        <div className="absolute inset-0 z-10 flex flex-col items-stretch justify-center rounded-[10px] bg-white/95 p-4">
          <p className="mb-2 text-xs" style={{ color: "var(--color-ink-soft)" }}>
            配置项目根路径（Agent 文件操作的工作目录）
          </p>
          <input
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            placeholder="例如：F:\\Projects\\MyGame"
            className="mb-3 w-full rounded border px-2 py-1 text-xs"
            style={{ borderColor: "var(--color-border-soft)" }}
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setPathModal(false)}
              className="rounded-lg border bg-white px-3 py-1.5 text-xs"
              style={{ borderColor: "var(--color-border-soft)" }}
            >
              取消
            </button>
            <button
              onClick={handlePathSave}
              disabled={!pathInput.trim() || rootPathMut.isPending}
              className="rounded-lg px-3 py-1.5 text-xs text-white disabled:opacity-50"
              style={{ backgroundColor: "var(--color-brand-500)" }}
            >
              保存
            </button>
          </div>
        </div>
      )}

      {/* Delete confirm overlay */}
      {deleteConfirm && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-[10px] bg-white/95 p-4">
          <p className="mb-2 text-xs" style={{ color: "var(--color-ink-soft)" }}>
            输入项目名 <strong>{project.name}</strong> 确认删除
          </p>
          <input
            value={deleteInput}
            onChange={(e) => setDeleteInput(e.target.value)}
            className="mb-3 w-full rounded border px-2 py-1 text-xs"
            style={{ borderColor: "var(--color-border-soft)" }}
            placeholder={project.name}
            autoFocus
          />
          <div className="flex gap-2">
            <button
              onClick={handleDelete}
              disabled={deleteInput !== project.name}
              className="rounded-lg bg-red-500 px-3 py-1.5 text-xs text-white disabled:opacity-50"
            >
              确认删除
            </button>
            <button
              onClick={() => {
                setDeleteConfirm(false);
                setDeleteInput("");
              }}
              className="rounded-lg border bg-white px-3 py-1.5 text-xs"
              style={{ borderColor: "var(--color-border-soft)" }}
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PathButton({
  locked,
  configured,
  onClick,
}: {
  locked: boolean;
  configured: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1 rounded-lg border bg-white px-3 py-2 text-sm transition-colors hover:bg-zinc-50"
      style={{
        borderColor: "var(--color-border-soft)",
        color: configured ? "var(--color-ink-label)" : "var(--color-ink-disabled)",
      }}
      title={configured ? "已配置路径" : "配置路径"}
    >
      {locked && (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="11" width="18" height="11" rx="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      )}
      路径
    </button>
  );
}

const statusDotColor: Record<string, string> = {
  pending: "#cbd5e1",
  running: "var(--color-brand-500)",
  done: "#10b981",
  failed: "#ef4444",
  validation_failed: "#f59e0b",
  aborted: "#737373",
  blocked: "#a78bfa",
  paused: "#facc15",
};

function TaskStatusIndicator({ status }: { status: string }) {
  if (status === "done") {
    return (
      <span className="text-[12px] font-bold" style={{ color: "#10b981" }} title="已完成">
        ✓
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="inline-flex gap-0.5" title="进行中">
        <span className="animate-pulse text-[12px]" style={{ color: "var(--color-brand-500)", animationDelay: "0ms" }}>·</span>
        <span className="animate-pulse text-[12px]" style={{ color: "var(--color-brand-500)", animationDelay: "200ms" }}>·</span>
        <span className="animate-pulse text-[12px]" style={{ color: "var(--color-brand-500)", animationDelay: "400ms" }}>·</span>
      </span>
    );
  }
  if (status === "failed" || status === "validation_failed") {
    return <span className="text-[12px]" style={{ color: "#ef4444" }} title={status}>!</span>;
  }
  // pending and everything else → empty (the left-side coloured dot already
  // carries the lower-fidelity status signal).
  return <span className="inline-block w-3" />;
}

/** Home-card task pill. Click toggles read-only detail; no inline edit
 *  here (full edit lives in the task page). Per PRD §2.3.9 & user
 *  feedback: 仅展开详情 / 不重复标题 / 不再可编辑. */
function TaskPill({ task, index }: { task: Task; index: number }) {
  const [expanded, setExpanded] = useState(false);
  // Resolve agent_id → role for display. Full agents list (no
  // assignable-filter) so even Plan-Maker-spawned agents surface
  // their real role, not a truncated id.
  const { data: agents } = useAgents();
  const agentLabel = task.agent_id
    ? (agents ?? []).find((a) => a.id === task.agent_id)?.role ?? task.agent_id.slice(-8)
    : "待指定";

  return (
    <div
      className="rounded-lg transition-colors"
      style={{ backgroundColor: "var(--color-surface-alt)" }}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-2 px-3 py-2 text-left"
      >
        <span
          className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: statusDotColor[task.status] ?? "#cbd5e1" }}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] font-medium" style={{ color: "var(--color-ink-soft)" }}>
            {`Task${index + 1}. ${task.title || "未命名"}`}
          </div>
          <div className="flex items-center gap-1.5 text-[10px]" style={{ color: "var(--color-ink-faint)" }}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
              <circle cx="12" cy="7" r="4" />
            </svg>
            <span className="truncate">{agentLabel}</span>
          </div>
        </div>
        <span className="mt-1 shrink-0">
          <TaskStatusIndicator status={task.status} />
        </span>
      </button>

      {/* Read-only detail panel — no inputs, no save/cancel buttons.
          Title is intentionally NOT repeated (already in the header row). */}
      {expanded && (
        <div
          className="px-3 pb-3 pt-1.5"
          style={{ borderTop: "1px solid var(--color-border-soft)" }}
        >
          <div
            className="whitespace-pre-wrap text-[11px] leading-relaxed"
            style={{ color: "var(--color-ink-muted)" }}
          >
            {task.detail?.trim() || "（暂无详情）"}
          </div>
        </div>
      )}
    </div>
  );
}

/** Inline "+ 新建任务" button rendered as the last item of a project card's
 *  task list. One click POSTs a placeholder task to this project; renaming
 *  / editing happens in the task page. */
function NewTaskButton({ projectId }: { projectId: string }) {
  const createMut = useCreateTask();
  return (
    <button
      type="button"
      onClick={() => {
        if (createMut.isPending) return;
        createMut.mutate({ project_id: projectId, title: "新任务" });
      }}
      disabled={createMut.isPending}
      className="flex w-full items-center justify-center gap-1 rounded-lg border border-dashed py-1.5 text-[11px] transition-colors hover:bg-white/60 disabled:opacity-50"
      style={{ borderColor: "var(--color-border-strong)", color: "var(--color-ink-muted)" }}
      title="为该项目创建一个空任务（可在任务页编辑）"
    >
      <span>+</span>
      <span>{createMut.isPending ? "创建中..." : "新建任务"}</span>
    </button>
  );
}

export default ProjectCard;
