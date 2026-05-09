import { usePermissions, useUpdatePermissions } from "../../queries/useConfigQuery";

const LABELS: Record<string, string> = {
  file_read: "文件读取",
  file_write: "文件写入",
  file_delete: "文件删除",
  file_modify: "文件修改",
  folder_read: "文件夹读取",
  dir_create: "目录创建",
  cmd_exec: "命令执行",
  bg_cmd: "后台命令",
  git: "Git 操作",
};

function PermissionMatrix() {
  const { data: permissions = [], isLoading } = usePermissions();
  const updateMutation = useUpdatePermissions();

  if (isLoading) return <div className="p-4 text-zinc-400">加载中...</div>;

  const handleToggle = (id: string, currentAllowed: boolean) => {
    updateMutation.mutate([{ id, allowed: !currentAllowed }]);
  };

  return (
    <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {(permissions as Record<string, unknown>[]).map((p) => (
        <div
          key={p.id as string}
          className="flex items-center justify-between px-4 py-3"
        >
          <div>
            <div className="text-sm font-medium">
              {LABELS[p.kind as string] ?? (p.kind as string)}
            </div>
            <div className="text-xs text-zinc-500">{p.kind as string}</div>
          </div>
          <button
            onClick={() => handleToggle(p.id as string, p.allowed as boolean)}
            className={`relative h-6 w-11 rounded-full transition-colors ${
              p.allowed ? "bg-blue-500" : "bg-zinc-300 dark:bg-zinc-700"
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
                p.allowed ? "translate-x-5" : ""
              }`}
            />
          </button>
        </div>
      ))}
    </div>
  );
}

export default PermissionMatrix;
