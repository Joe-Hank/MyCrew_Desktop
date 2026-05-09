import { usePermissions, useUpdatePermissions } from "../../queries/useConfigQuery";

function PermissionTable() {
  const { data: permissions = [], isLoading } = usePermissions();
  const updateMutation = useUpdatePermissions();

  if (isLoading) return <div className="py-8 text-center text-sm text-zinc-400">加载中...</div>;

  const handleToggle = (id: string, currentAllowed: boolean) => {
    updateMutation.mutate([{ id, allowed: !currentAllowed }]);
  };

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <div className="grid grid-cols-[1fr_auto] gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        <span className="text-xs font-medium text-zinc-400">名称</span>
        <span className="text-xs font-medium text-zinc-400">开关</span>
      </div>

      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {(permissions as Record<string, unknown>[]).map((p) => (
          <div
            key={p.id as string}
            className="grid grid-cols-[1fr_auto] items-center gap-2 px-4 py-3"
          >
            <span className="text-sm">{p.kind as string}</span>
            <button
              onClick={() => handleToggle(p.id as string, p.allowed as boolean)}
              disabled={updateMutation.isPending}
              className={`relative h-7 w-14 rounded-full transition-colors ${
                p.allowed ? "bg-green-500" : "bg-zinc-300 dark:bg-zinc-600"
              }`}
              aria-label={`${p.kind} ${p.allowed ? "已启用" : "已禁用"}`}
            >
              <span
                className={`absolute top-0.5 left-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform ${
                  p.allowed ? "translate-x-7" : ""
                }`}
              />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default PermissionTable;
