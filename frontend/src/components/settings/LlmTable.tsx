import { useLlmProviders, type LlmProvider } from "../../queries/useLlmQuery";
import { useDeleteLlmProvider } from "../../queries/useLlmQuery";

const COLUMNS = ["名称", "平台", "API KEY", "URL", "MODEL", "操作"] as const;

function LlmTable({ onEdit }: { onEdit: (p: LlmProvider) => void }) {
  const { data: providers = [], isLoading } = useLlmProviders();
  const deleteMutation = useDeleteLlmProvider();

  if (isLoading) return <div className="py-8 text-center text-sm text-zinc-400">加载中...</div>;

  if (providers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-16 text-zinc-400">
        <span className="text-3xl">🤖</span>
        <p className="text-sm">暂无 LLM 配置</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      {/* Header */}
      <div className="grid grid-cols-[1.2fr_1fr_1.5fr_1.5fr_1fr_auto] gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        {COLUMNS.map((col) => (
          <span key={col} className="text-xs font-medium text-zinc-400">{col}</span>
        ))}
      </div>

      {/* Rows */}
      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {(providers as LlmProvider[]).map((p) => (
          <div
            key={p.id}
            className="group grid grid-cols-[1.2fr_1fr_1.5fr_1.5fr_1fr_auto] items-center gap-2 px-4 py-3 transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
          >
            <div className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-500" />
              <span className="text-sm font-medium">{p.name}</span>
            </div>
            <span className="text-xs text-zinc-600 dark:text-zinc-400">{p.type}</span>
            <span className="truncate text-xs text-zinc-600 dark:text-zinc-400">
              {p.api_key_ref ? `sk-${"*".repeat(16)}${p.api_key_ref.slice(-4)}` : "—"}
            </span>
            <span className="truncate text-xs text-zinc-600 dark:text-zinc-400">
              {p.base_url || "—"}
            </span>
            <span className="text-xs text-zinc-600 dark:text-zinc-400">
              {p.models?.[0]?.model_name || "—"}
            </span>
            <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              <button
                onClick={() => onEdit(p)}
                className="rounded-2xl border border-zinc-200 bg-white px-3 py-1 text-xs text-zinc-600 shadow-sm transition-colors hover:bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
              >
                编辑
              </button>
              <button
                onClick={() => deleteMutation.mutate(p.id)}
                className="rounded-2xl bg-red-400 px-3 py-1 text-xs text-white shadow-sm transition-colors hover:bg-red-500"
              >
                删除
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default LlmTable;
