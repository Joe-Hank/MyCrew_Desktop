import { useState, useCallback, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useProject, type Task } from "../queries/useProjectQuery";
import { useRetryTask } from "../queries/useWorkflowQuery";
import { useEvent } from "../hooks/useEvent";
import { useQueryClient } from "@tanstack/react-query";
import TaskHeader from "../components/task/TaskHeader";
import Blueprint from "../components/task/Blueprint";
import TaskEditModal from "../components/task/TaskEditModal";
import AgentChatDrawer from "../components/task/AgentChatDrawer";
import IoViewerDrawer from "../components/task/IoViewerDrawer";
import type { TaskAction } from "../components/task/TaskNode";

type DrawerState =
  | null
  | { kind: "edit"; task: Task }
  | { kind: "agent_chat"; task: Task }
  | { kind: "view_io"; task: Task; direction: "in" | "out" };

function TaskPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { data: project, isLoading } = useProject(projectId);
  const retryTask = useRetryTask();
  const qc = useQueryClient();
  const [drawer, setDrawer] = useState<DrawerState>(null);
  const [retryConfirm, setRetryConfirm] = useState<Task | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  // Auto-select first task on project load
  useEffect(() => {
    if (project?.tasks && project.tasks.length > 0 && !selectedTaskId) {
      const first = project.tasks[0];
      if (first) setSelectedTaskId(first.id);
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

  function handleAction(action: TaskAction) {
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
  }

  function handleSelect(task: Task) {
    setSelectedTaskId(task.id);
  }

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
          <Blueprint
            tasks={tasks}
            selectedTaskId={selectedTaskId}
            projectRunning={projectRunning}
            onSelect={handleSelect}
            onAction={handleAction}
          />
        </div>

        {/* Side drawer */}
        {drawer?.kind === "agent_chat" && (
          <div className="w-[340px]">
            <AgentChatDrawer task={drawer.task} onClose={() => setDrawer(null)} />
          </div>
        )}

        {drawer?.kind === "view_io" && (
          <div className="w-[340px]">
            <IoViewerDrawer
              task={drawer.task}
              initialDirection={drawer.direction}
              onClose={() => setDrawer(null)}
            />
          </div>
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
