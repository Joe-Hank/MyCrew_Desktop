import { useState, useCallback, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useProject, type Task } from "../queries/useProjectQuery";
import { useRetryTask } from "../queries/useWorkflowQuery";
import { useEvent } from "../hooks/useEvent";
import { useQueryClient } from "@tanstack/react-query";
import { usePrefsStore } from "../stores/usePrefsStore";
import TaskHeader from "../components/task/TaskHeader";
import CanvasBlueprint from "../components/task/CanvasBlueprint";
import TaskEditModal from "../components/task/TaskEditModal";
import AgentChatDrawer from "../components/task/AgentChatDrawer";
import IoViewerDrawer from "../components/task/IoViewerDrawer";
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
  const qc = useQueryClient();
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [retryConfirm, setRetryConfirm] = useState<Task | null>(null);
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
  const handleAction = useCallback((action: TaskAction) => {
    switch (action.kind) {
      case "edit":
        setDrawer({ kind: "edit", task: action.task });
        break;
      case "retry":
        setRetryConfirm(action.task);
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
  }, []);

  // PM v4: sub-card actions route through the same drawer machinery as
  // task-level actions, but carry an extra stepIndex so the backend
  // scopes guidance / IO viewer to a single Crew step.
  const handleSubStepAction = useCallback((action: SubStepAction) => {
    switch (action.kind) {
      case "edit":
        // Edit-from-step is a Head-only Q6 path: open the Head's spec
        // (sub/0_head_out.json) for direct JSON editing. For now route
        // to the same TaskEditModal — Stage G will refine.
        setDrawer({ kind: "edit", task: action.task });
        break;
      case "retry":
        setRetryConfirm(action.task);
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
  }, []);

  const handleSelect = useCallback((task: Task) => {
    setSelectedTaskId(task.id);
  }, []);

  function handleRetryConfirmed() {
    if (!retryConfirm || !projectId) return;
    retryTask.mutate({ projectId, taskId: retryConfirm.id });
    setRetryConfirm(null);
  }

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

      {/* Retry confirmation */}
      {retryConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div
            className="w-full max-w-xs rounded-lg bg-white p-5 shadow-xl"
            style={{ border: "1px solid var(--color-border-soft)" }}
          >
            <h3 className="mb-2 text-sm font-semibold">确认重新执行</h3>
            <p className="mb-4 text-xs" style={{ color: "var(--color-ink-faint)" }}>
              确定要重新执行任务「{retryConfirm.title}」吗？下游依赖任务可能也会受影响。
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setRetryConfirm(null)}
                className="rounded-lg border px-3 py-1.5 text-xs"
                style={{ borderColor: "var(--color-border-soft)" }}
              >
                取消
              </button>
              <button
                onClick={handleRetryConfirmed}
                disabled={retryTask.isPending}
                className="rounded-lg bg-orange-500 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                确认重跑
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default TaskPage;
