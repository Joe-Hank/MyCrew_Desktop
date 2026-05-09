import { useState } from "react";
import type { Task } from "../../queries/useProjectQuery";
import { useUpdateTask } from "../../queries/useWorkflowQuery";

function TaskEditModal({
  task,
  onClose,
}: {
  task: Task;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(task.title);
  const [detail, setDetail] = useState(task.detail);
  const update = useUpdateTask();

  async function handleSave() {
    const changes: Record<string, string> = {};
    if (title !== task.title) changes.title = title;
    if (detail !== task.detail) changes.detail = detail;
    if (Object.keys(changes).length === 0) {
      onClose();
      return;
    }
    await update.mutateAsync({ taskId: task.id, ...changes });
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="w-full max-w-md rounded-lg border border-zinc-200 bg-white p-5 shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
        <h3 className="mb-3 text-sm font-semibold">编辑任务</h3>

        <label className="mb-1 block text-[11px] text-zinc-500">标题</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="mb-3 w-full rounded border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-800"
        />

        <label className="mb-1 block text-[11px] text-zinc-500">详情</label>
        <textarea
          value={detail}
          onChange={(e) => setDetail(e.target.value)}
          rows={4}
          className="mb-4 w-full resize-none rounded border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-800"
        />

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded border border-zinc-300 px-3 py-1.5 text-xs dark:border-zinc-600"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={update.isPending || !title.trim()}
            className="rounded bg-blue-500 px-4 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          >
            {update.isPending ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default TaskEditModal;
