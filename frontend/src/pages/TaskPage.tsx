import { useState, useCallback, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useProject, type Task } from "../queries/useProjectQuery";
import { useRetryTask, useUpdateTask } from "../queries/useWorkflowQuery";
import { useEvent } from "../hooks/useEvent";
import { useQueryClient } from "@tanstack/react-query";
import { usePrefsStore } from "../stores/usePrefsStore";
import TaskHeader from "../components/task/TaskHeader";
import CanvasBlueprint from "../components/task/CanvasBlueprint";
import TaskEditModal from "../components/task/TaskEditModal";
import AgentChatDrawer from "../components/task/AgentChatDrawer";
import IoViewerDrawer from "../components/task/IoViewerDrawer";
import { useDismissibleConfirm } from "../components/common/ConfirmDialog";
import type { TaskAction } from "../components/task/TaskNode";
import type { SubStepAction } from "../components/task/SubAgentCard";

type DrawerState =
  | null
  | { kind: "edit"; task: Task }
  | { kind: "agent_chat"; task: Task; stepIndex?: number; agentId?: string }
  | { kind: "view_io"; task: Task; direction: "in" | "out"; stepIndex?: number };

function TaskPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const lastProjectId = usePrefsStore((s) => s.lastProjectId);
  const setLastProjectId = usePrefsStore((s) => s.setLastProjectId);
  const { data: project, isLoading } = useProject(projectId);
  const retryTask = useRetryTask();
  const updateTask = useUpdateTask();
  const qc = useQueryClient();
  const confirm = useDismissibleConfirm();
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  // ── Last-opened project persistence ────────────────────────────
  //
  // Hitting `/tasks` (no id) — happens when the user clicks "任务" in
  // the sidebar or restarts the app — restores whichever project was
  // last viewed. This keeps the canvas state across navigation and
  // across app restarts (the id is persisted to localStorage via the
  // prefs store).
  useEffect(() => {
    if (!projectId && lastProjectId) {
      navigate(`/tasks/${lastProjectId}`, { replace: true });
    }
  }, [projectId, lastProjectId, navigate]);

  // Whenever the URL settles on a real project id, remember it.
  useEffect(() => {
    if (projectId && projectId !== lastProjectId) {
      setLastProjectId(projectId);
    }
  }, [projectId, lastProjectId, setLastProjectId]);

  // If the persisted lastProjectId points to a project that no longer
  // exists (deleted from home grid while away), clear it so the next
  // visit to /tasks shows the empty-state instead of looping on 404.
  useEffect(() => {
    if (projectId && !isLoading && project === null && projectId === lastProjectId) {
      setLastProjectId(null);
    }
  }, [projectId, isLoading, project, lastProjectId, setLastProjectId]);

  // Auto-select first task ONCE per project load. Without the
  // didAutoSelect guard, clicking empty pane (which calls
  // setSelectedTaskId(null)) would re-trigger this effect and snap the
  // selection back to task 1 — defeating the "click blank to focus
  // project" UX.
  const didAutoSelect = useRef(false);
  useEffect(() => {
    setSelectedTaskId(null);
    didAutoSelect.current = false;
  }, [projectId]);
  useEffect(() => {
    if (
      project?.tasks
      && project.tasks.length > 0
      && !selectedTaskId
      && !didAutoSelect.current
    ) {
      const first = project.tasks[0];
      if (first) {
        setSelectedTaskId(first.id);
        didAutoSelect.current = true;
      }
    }
  }, [project, selectedTaskId]);

  const handleWsTaskEvent = useCallback(() => {
    if (projectId) qc.invalidateQueries({ queryKey: ["project", projectId] });
  }, [projectId, qc]);

  useEvent("task.started", handleWsTaskEvent);
  useEvent("task.completed", handleWsTaskEvent);
  useEvent("task.failed", handleWsTaskEvent);
  useEvent("task.paused", handleWsTaskEvent);
  useEvent("task.blocked", handleWsTaskEvent);
  useEvent("task.validation.failed", handleWsTaskEvent);
  useEvent("project.started", handleWsTaskEvent);
  useEvent("project.paused", handleWsTaskEvent);
  useEvent("project.resumed", handleWsTaskEvent);
  useEvent("project.completed", handleWsTaskEvent);
  useEvent("project.aborted", handleWsTaskEvent);
  useEvent("project.progress", handleWsTaskEvent);

  // Stable identity so the canvas doesn't recompute its node-data memo
  // on every parent re-render (a WS event firing in the background was
  // re-creating onSelect/onAction → cascading through ReactFlow and
  // briefly disconnecting edges during a drag).
  // Shared confirm flow used by both task-level and sub-card retry
  // actions. Stage B (2026-05-16) replaces the old inline modal with
  // the dismissible-dialog framework: the user picks whether to wipe
  // the previous run's sub/ + out.* on disk, and may tick "不再显示"
  // to lock in that choice for future retries.
  const askRetryAndRun = useCallback(
    async (task: Task) => {
      if (!projectId) return;

      // Stage D: if this task already finished cleanly AND has done
      // downstream tasks, warn that the downstream will keep using its
      // pre-retry artifacts (we intentionally don't cascade-reset them
      // — user said: 不用管它，只重做指定任务，给用户弹窗提醒).
      // Read project.tasks lazily — `const tasks` is declared after
      // this useCallback, so we resolve it from `project` directly.
      const allTasks = project?.tasks ?? [];
      const downstreamDoneCount =
        task.status === "done"
          ? allTasks.filter(
              (t) => t.status === "done" && (t.deps || []).includes(task.id),
            ).length
          : 0;
      if (downstreamDoneCount > 0) {
        const downstreamRes = await confirm({
          dialogId: "retry.downstream_warning",
          title: "下游任务已完成，仍要重做当前任务？",
          body: (
            <>
              <p>
                有 {downstreamDoneCount} 个下游任务已经 done。重做
                「{task.title}」<strong>只会跑当前任务</strong>，
                下游不会自动重跑，它们引用的还是当前任务上一轮的产物。
              </p>
              <p className="mt-2 text-xs text-gray-500">
                如果你只是想换个产物给下游用，没问题；如果下游也要按新产物重新跑，
                请到下游任务卡上分别点击重试。
              </p>
            </>
          ),
          options: [
            { value: "proceed", label: "知道了，继续", primary: true },
            { value: "cancel", label: "取消", tone: "subtle" },
          ],
          allowDismiss: true,
        });
        if (!downstreamRes.choice || downstreamRes.choice === "cancel") return;
      }

      const result = await confirm({
        dialogId: "retry.cleanup_artifacts",
        title: `重新执行「${task.title}」？`,
        body: (
          <>
            <p>下游依赖任务可能也会受影响。</p>
            <p className="mt-2 text-xs text-gray-500">
              产物清除：会删掉本任务上一轮的 <code>sub/</code> + <code>out.json/md</code>，
              避免下次校验把残留文件当成「已生成」。如果你确认上轮输出本身没问题、只是下游挂了，
              可以选保留。
            </p>
          </>
        ),
        options: [
          { value: "cleanup", label: "清除产物并重试（推荐）", primary: true },
          { value: "keep", label: "保留产物直接重试" },
          { value: "cancel", label: "取消", tone: "subtle" },
        ],
        allowDismiss: true,
      });
      if (!result.choice || result.choice === "cancel") return;
      try {
        // Use mutateAsync so we can surface the real backend error
        // (previously .mutate() swallowed failures — the user saw
        // the dialog close and assumed it worked).
        await retryTask.mutateAsync({
          projectId,
          taskId: task.id,
          cleanupArtifacts: result.choice === "cleanup",
        });
      } catch (exc) {
        const msg = exc instanceof Error ? exc.message : String(exc);
        alert(`重试失败：${msg}`);
      }
    },
    [confirm, projectId, retryTask, project?.tasks],
  );

  // Stage C: AgentChatDrawer hands us the user's guidance messages
  // ("用 64x64 不是 32x32" etc). We offer to append them to the task's
  // detail (so the retry prompt actually sees them) before triggering
  // the same retry flow as a plain retry click.
  const askApplyGuidanceAndRetry = useCallback(
    async (task: Task, userMessages: string[]) => {
      if (!projectId || userMessages.length === 0) return;

      const guidanceBlock = formatGuidanceAppendix(userMessages);
      const result = await confirm({
        dialogId: "retry.guidance_to_detail",
        title: "把对话反馈写进任务详情？",
        body: (
          <>
            <p>下面这段会追加到任务详情末尾，下次重试时 Agent 就能看到：</p>
            <pre
              className="mt-2 max-h-48 overflow-auto rounded-md bg-gray-50 p-2 text-[11px] leading-relaxed text-gray-700"
              style={{ whiteSpace: "pre-wrap" }}
            >
              {guidanceBlock}
            </pre>
          </>
        ),
        options: [
          { value: "append", label: "追加并重试（推荐）", primary: true },
          { value: "skip", label: "不追加直接重试" },
          { value: "cancel", label: "取消", tone: "subtle" },
        ],
        allowDismiss: true,
      });
      if (!result.choice || result.choice === "cancel") return;

      if (result.choice === "append") {
        // The Task type stores `detail` as nullable; existing content
        // is preserved with a blank-line separator so successive rounds
        // accumulate readably instead of running together.
        const merged = task.detail
          ? `${task.detail.trimEnd()}\n\n${guidanceBlock}`
          : guidanceBlock;
        try {
          await updateTask.mutateAsync({ taskId: task.id, detail: merged });
        } catch (err) {
          // Surface but don't block — the user still wanted to retry.
          console.warn("failed to append guidance to task.detail", err);
        }
      }

      // Close the chat drawer + invoke the existing cleanup confirm.
      setDrawer(null);
      await askRetryAndRun({ ...task, detail: result.choice === "append"
        ? formatGuidanceAppendix(userMessages)
        : task.detail });
    },
    [confirm, projectId, updateTask, askRetryAndRun],
  );

  const handleAction = useCallback(
    (action: TaskAction) => {
      switch (action.kind) {
        case "edit":
          setDrawer({ kind: "edit", task: action.task });
          break;
        case "retry":
          void askRetryAndRun(action.task);
          break;
        case "agent_chat":
          setDrawer({ kind: "agent_chat", task: action.task });
          break;
        case "view_io":
          setDrawer({ kind: "view_io", task: action.task, direction: action.direction });
          break;
        case "pause":
          break;
      }
    },
    [askRetryAndRun],
  );

  // PM v4: sub-card actions route through the same drawer machinery as
  // task-level actions, but carry an extra stepIndex so the backend
  // scopes guidance / IO viewer to a single Crew step.
  const handleSubStepAction = useCallback(
    (action: SubStepAction) => {
      switch (action.kind) {
        case "edit":
          // Edit-from-step is a Head-only Q6 path: open the Head's spec
          // (sub/0_head_out.json) for direct JSON editing. For now route
          // to the same TaskEditModal — Stage G will refine.
          setDrawer({ kind: "edit", task: action.task });
          break;
        case "retry":
          void askRetryAndRun(action.task);
          break;
        case "pause":
          // Pause the Crew (task-level). Backend's _run_crew checks the
          // pause flag at every step boundary.
          break;
        case "sub_chat":
          setDrawer({
            kind: "agent_chat",
            task: action.task,
            stepIndex: action.stepIndex,
            agentId: action.agentId,
          });
          break;
        case "sub_view_io":
          setDrawer({
            kind: "view_io",
            task: action.task,
            direction: "out",
            stepIndex: action.stepIndex,
          });
          break;
      }
    },
    [askRetryAndRun],
  );

  const handleSelect = useCallback((task: Task) => {
    setSelectedTaskId(task.id);
  }, []);

  if (!projectId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm" style={{ color: "var(--color-ink-ghost)" }}>请从主页选择一个项目</p>
        <button
          onClick={() => navigate("/")}
          className="rounded-lg px-4 py-1.5 text-sm font-medium text-white"
          style={{ backgroundColor: "var(--color-brand-500)" }}
        >
          返回主页
        </button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div
          className="h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
          style={{ borderColor: "var(--color-brand-500)", borderTopColor: "transparent" }}
        />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm" style={{ color: "var(--color-ink-ghost)" }}>项目未找到</p>
        <button
          onClick={() => navigate("/")}
          className="rounded-lg px-4 py-1.5 text-sm font-medium text-white"
          style={{ backgroundColor: "var(--color-brand-500)" }}
        >
          返回主页
        </button>
      </div>
    );
  }

  const tasks = project.tasks ?? [];
  const selectedTask = tasks.find((t) => t.id === selectedTaskId) ?? null;
  const projectRunning = project.state === "running";
  const hasDrawer = drawer !== null;

  return (
    <div className="flex h-full flex-col">
      <TaskHeader project={project} selectedTask={selectedTask} />

      <div className="flex flex-1 overflow-hidden">
        {/* DAG area */}
        <div
          className={`flex-1 overflow-hidden ${hasDrawer ? "" : ""}`}
          style={hasDrawer ? { borderRight: "1px solid var(--color-border-soft)" } : {}}
        >
          <CanvasBlueprint
            projectId={project.id}
            tasks={tasks}
            selectedTaskId={selectedTaskId}
            projectRunning={projectRunning}
            onSelect={handleSelect}
            onAction={handleAction}
            onSubStepAction={handleSubStepAction}
            onDeselect={() => setSelectedTaskId(null)}
          />
        </div>

        {/* Side drawer — width tuned to match the Plan Maker chat column
            so the two LLM-chat surfaces feel like the same product. */}
        {drawer?.kind === "agent_chat" && (
          <div className="w-[400px] shrink-0">
            <AgentChatDrawer
              task={drawer.task}
              stepIndex={drawer.stepIndex}
              agentId={drawer.agentId}
              onClose={() => setDrawer(null)}
              onApplyAndRetry={(userMessages) =>
                void askApplyGuidanceAndRetry(drawer.task, userMessages)
              }
            />
          </div>
        )}

        {drawer?.kind === "view_io" && (
          // No wrapper width — IoViewerDrawer manages its own width via
          // usePrefsStore so the user-dragged size sticks across opens.
          <IoViewerDrawer
            task={drawer.task}
            initialDirection={drawer.direction}
            stepIndex={drawer.stepIndex}
            onClose={() => setDrawer(null)}
          />
        )}
      </div>

      {/* Edit modal */}
      {drawer?.kind === "edit" && (
        <TaskEditModal task={drawer.task} onClose={() => setDrawer(null)} />
      )}

      {/* Retry uses the dismissible ConfirmDialog (Stage B, 2026-05-16);
          the previous inline modal was removed in favor of the shared
          provider mounted at app root. */}
    </div>
  );
}

// Stable header used to fence guidance appendices written by Stage C.
// Future passes can grep for it to strip the block when running an
// "undo guidance" action, or to dedupe across multiple chat rounds.
const GUIDANCE_HEADER = "--- 用户补充指导（来自任务诊断对话） ---";

function formatGuidanceAppendix(userMessages: string[]): string {
  const body = userMessages
    .map((m) => `- ${m.replace(/\s+/g, " ").trim()}`)
    .join("\n");
  return `${GUIDANCE_HEADER}\n${body}`;
}

export default TaskPage;
