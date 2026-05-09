import { useLlmProviders, LLM_TYPES, type LlmProvider } from "../../queries/useLlmQuery";

function LlmList({ onSelect }: { onSelect: (id: string) => void }) {
  const { data: providers = [], isLoading } = useLlmProviders();

  if (isLoading) return <div className="p-4 text-zinc-400">加载中...</div>;

  if (providers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-12 text-zinc-400">
        <span className="text-3xl">🤖</span>
        <p className="text-sm">暂无 LLM 配置</p>
        <p className="text-xs">点击右上角"+ 新建"添加 LLM 提供商</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
      {(providers as LlmProvider[]).map((p) => {
        const typeLabel = LLM_TYPES.find((t) => t.value === p.type)?.label ?? p.type;
        const modelCount = p.models?.length ?? 0;
        return (
          <button
            key={p.id}
            onClick={() => onSelect(p.id)}
            className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{p.name}</span>
                <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800">
                  {typeLabel}
                </span>
              </div>
              <div className="mt-0.5 flex items-center gap-2 text-[11px] text-zinc-400">
                <span>{modelCount} 个模型</span>
                {p.base_url && (
                  <span className="truncate max-w-[200px]">{p.base_url}</span>
                )}
              </div>
            </div>
            <span className="text-zinc-300 dark:text-zinc-600">›</span>
          </button>
        );
      })}
    </div>
  );
}

export default LlmList;
