import { usePermissions, useUpdatePermissions } from "../../queries/useConfigQuery";

const PERMISSION_INFO: Record<string, { label: string; desc: string }> = {
  file_read: { label: "文件读取", desc: "允许 Agent 读取文件内容" },
  file_write: { label: "文件写入", desc: "允许 Agent 创建新文件" },
  file_delete: { label: "文件删除", desc: "允许 Agent 删除文件" },
  file_modify: { label: "文件修改", desc: "允许 Agent 修改已有文件" },
  folder_read: { label: "文件夹读取", desc: "允许 Agent 列出目录内容" },
  dir_create: { label: "目录创建", desc: "允许 Agent 创建新目录" },
  cmd_exec: { label: "命令执行", desc: "允许 Agent 执行系统命令" },
  bg_cmd: { label: "后台命令", desc: "允许 Agent 启动后台进程" },
  git: { label: "Git 操作", desc: "允许 Agent 执行 Git 命令" },
};

function PermissionTable() {
  const { data: permissions = [], isLoading } = usePermissions();
  const updateMutation = useUpdatePermissions();

  if (isLoading) {
    return <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>加载中...</div>;
  }

  function handleToggle(id: string, currentAllowed: boolean) {
    updateMutation.mutate([{ id, allowed: !currentAllowed }]);
  }

  return (
    <div className="space-y-3">
      <div
        className="rounded-lg px-4 py-2 text-xs"
        style={{
          backgroundColor: "rgba(245, 158, 11, 0.12)",
          color: "#92400e",
        }}
      >
        ⚠️ 这些权限控制 Agent 在执行任务时可以进行的系统操作。关闭某项权限后，相关 Tool/MCP 调用会被立即拦截。
      </div>

      <div className="overflow-hidden rounded-xl bg-white" style={{ border: "1px solid var(--color-border-soft)" }}>
        {(permissions as Record<string, unknown>[]).map((p, i) => {
          const info = PERMISSION_INFO[p.kind as string];
          return (
            <div
              key={p.id as string}
              className="flex items-center justify-between px-5 py-3"
              style={i === 0 ? {} : { borderTop: "1px solid var(--color-border-soft)" }}
            >
              <div>
                <div className="text-sm font-medium" style={{ color: "var(--color-ink-soft)" }}>
                  {info?.label ?? (p.kind as string)}
                </div>
                <div className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                  {info?.desc ?? (p.kind as string)}
                </div>
              </div>
              <button
                onClick={() => handleToggle(p.id as string, p.allowed as boolean)}
                disabled={updateMutation.isPending}
                className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors"
                style={{ backgroundColor: p.allowed ? "#10b981" : "var(--color-surface-alt)" }}
              >
                <span
                  className="absolute h-5 w-5 rounded-full bg-white shadow-sm transition-transform"
                  style={{ transform: p.allowed ? "translateX(24px)" : "translateX(2px)" }}
                />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default PermissionTable;
