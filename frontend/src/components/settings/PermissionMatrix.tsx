import { usePermissions, useUpdatePermissions } from "../../queries/useConfigQuery";

const PERMISSION_INFO: Record<string, { label: string; desc: string; icon: string }> = {
  file_read: { label: "文件读取", desc: "允许 Agent 读取文件内容", icon: "📄" },
  file_write: { label: "文件写入", desc: "允许 Agent 创建新文件", icon: "✏️" },
  file_delete: { label: "文件删除", desc: "允许 Agent 删除文件", icon: "🗑️" },
  file_modify: { label: "文件修改", desc: "允许 Agent 修改已有文件", icon: "📝" },
  folder_read: { label: "文件夹读取", desc: "允许 Agent 列出目录内容", icon: "📁" },
  dir_create: { label: "目录创建", desc: "允许 Agent 创建新目录", icon: "📂" },
  cmd_exec: { label: "命令执行", desc: "允许 Agent 执行系统命令", icon: "⚡" },
  bg_cmd: { label: "后台命令", desc: "允许 Agent 启动后台进程", icon: "🔄" },
  git: { label: "Git 操作", desc: "允许 Agent 执行 Git 命令", icon: "🔀" },
};

function PermissionMatrix() {
  const { data: permissions = [], isLoading } = usePermissions();
  const updateMutation = useUpdatePermissions();

  if (isLoading) return <div className="p-4 text-zinc-400">加载中...</div>;

  const handleToggle = (id: string, currentAllowed: boolean) => {
    updateMutation.mutate([{ id, allowed: !currentAllowed }]);
  };

  return (
    <div className="p-4">
      <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:bg-amber-950/30 dark:text-amber-400">
        💡 这些权限控制 Agent 在执行任务时可以进行的系统操作。关闭某项权限后，相关 Tool/MCP 调用会被立即拦截。
      </div>

      <div className="divide-y divide-zinc-100 rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-700">
        {(permissions as Record<string, unknown>[]).map((p) => {
          const info = PERMISSION_INFO[p.kind as string];
          return (
            <div
              key={p.id as string}
              className="flex items-center justify-between px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <span className="text-base">{info?.icon ?? "🔒"}</span>
                <div>
                  <div className="text-sm font-medium">
                    {info?.label ?? (p.kind as string)}
                  </div>
                  <div className="text-[11px] text-zinc-500">
                    {info?.desc ?? (p.kind as string)}
                  </div>
                </div>
              </div>
              <button
                onClick={() => handleToggle(p.id as string, p.allowed as boolean)}
                disabled={updateMutation.isPending}
                className={`relative h-6 w-11 rounded-full transition-colors ${
                  p.allowed ? "bg-blue-500" : "bg-zinc-300 dark:bg-zinc-700"
                }`}
                aria-label={`${info?.label ?? p.kind} ${p.allowed ? "已启用" : "已禁用"}`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                    p.allowed ? "translate-x-5" : ""
                  }`}
                />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default PermissionMatrix;
