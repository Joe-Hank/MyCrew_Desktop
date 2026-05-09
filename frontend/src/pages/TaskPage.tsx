import { useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useProject, type Task } from "../queries/useProjectQuery";
import { useRetryTask } from "../queries/useWorkflowQuery";
import { useEvent } from "../hooks/useEvent";
import { useQueryClient } from "@tanstack/react-query";
import ProjectHeader from "../components/task/ProjectHeader";
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
        // Pause handled via workflow — for now treat as noop placeholder
        break;
    }
  }

  function handleRetryConfirmed() {
    if (!retryConfirm || !projectId) return;
    retryTask.mutate({ projectId, taskId: retryConfirm.id });
    setRetryConfirm(null);
  }

  if (!projectId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm text-zinc-400">请从主页选择一个项目</p>
        <button
          onClick={() => navigate("/")}
          className="rounded bg-blue-500 px-4 py-1.5 text-xs font-medium text-white"
        >
          返回主页
        </button>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm text-zinc-400">项目未找到</p>
        <button
          onClick={() => navigate("/")}
          className="rounded bg-blue-500 px-4 py-1.5 text-xs font-medium text-white"
        >
          返回主页
        </button>
      </div>
    );
  }

  const tasks = project.tasks ?? [];
  const projectRunning = project.state === "running";
  const hasDrawer = drawer !== null;
  const drawerWidth = hasDrawer ? "w-[340px]" : "";

  return (
    <div className="flex h-full flex-col">
      <ProjectHeader project={project} />

      <div className="flex flex-1 overflow-hidden">
        {/* DAG area */}
        <div className={`flex-1 overflow-auto ${hasDrawer ? "border-r border-zinc-200 dark:border-zinc-700" : ""}`}>
          <Blueprint
            tasks={tasks}
            projectRunning={projectRunning}
            onAction={handleAction}
          />
        </div>

        {/* Side drawer */}
        {drawer?.kind === "agent_chat" && (
          <div className={drawerWidth}>
            <AgentChatDrawer task={drawer.task} onClose={() => setDrawer(null)} />
          </div>
        )}

        {drawer?.kind === "view_io" && (
          <div className={drawerWidth}>
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
          <div className="w-full max-w-xs rounded-lg border border-zinc-200 bg-white p-5 shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
            <h3 className="mb-2 text-sm font-semibold">确认重新执行</h3>
            <p className="mb-4 text-xs text-zinc-500">
              确定要重新执行任务「{retryConfirm.title}」吗？下游依赖任务可能也会受影响。
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setRetryConfirm(null)}
                className="rounded border border-zinc-300 px-3 py-1.5 text-xs dark:border-zinc-600"
              >
                取消
              </button>
              <button
                onClick={handleRetryConfirmed}
                disabled={retryTask.isPending}
                className="rounded bg-orange-500 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
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
