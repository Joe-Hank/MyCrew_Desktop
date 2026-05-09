import { useLlmProviders } from "../../queries/useLlmQuery";

function LlmList({ onSelect }: { onSelect: (id: string) => void }) {
  const { data: providers = [], isLoading } = useLlmProviders();

  if (isLoading) return <div className="p-4 text-zinc-400">加载中...</div>;

  if (providers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-8 text-zinc-400">
        <p>暂无 LLM 配置</p>
        <p className="text-xs">点击左上角"新建"添加 LLM 提供商</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
      {(providers as Record<string, unknown>[]).map((p) => (
        <button
          key={p.id as string}
          onClick={() => onSelect(p.id as string)}
          className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-zinc-100 dark:hover:bg-zinc-800/50"
        >
          <div>
            <div className="text-sm font-medium">{p.name as string}</div>
            <div className="text-xs text-zinc-500">{p.type as string}</div>
          </div>
          <div className="text-xs text-zinc-400">
            {((p.models as unknown[]) ?? []).length} 个模型
          </div>
        </button>
      ))}
    </div>
  );
}

export default LlmList;
