import { useLlmProviders, useDeleteLlmProvider, type LlmProvider, LLM_TYPES } from "../../queries/useLlmQuery";
import RowActionsMenu from "../common/RowActionsMenu";

const GRID = "grid-cols-[20px_1.2fr_1fr_1.6fr_1.4fr_1fr_60px]";

function mask(key: string | null): string {
  if (!key) return "—";
  if (key.length <= 8) return "****";
  return `${key.slice(0, 3)}-${"*".repeat(Math.max(8, key.length - 7))}${key.slice(-4)}`;
}

function typeLabel(t: string): string {
  return LLM_TYPES.find((x) => x.value === t)?.label ?? t;
}

function LlmTable({ onEdit }: { onEdit: (p: LlmProvider) => void }) {
  const { data: providers, isLoading } = useLlmProviders();
  const deleteMut = useDeleteLlmProvider();

  const items = providers ?? [];

  if (isLoading) {
    return <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>加载中...</div>;
  }

  return (
    <div className="overflow-hidden rounded-xl bg-white" style={{ border: "1px solid var(--color-border-soft)" }}>
      <div
        className={`grid ${GRID} items-center gap-2 px-5 py-3`}
        style={{ borderBottom: "1px solid var(--color-border-soft)" }}
      >
        <span />
        {["名称", "平台", "API KEY", "URL", "MODEL", "操作"].map((c) => (
          <span key={c} className="text-xs uppercase tracking-wide" style={{ color: "var(--color-ink-ghost)" }}>
            {c}
          </span>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>
          暂无 LLM 配置
        </div>
      ) : (
        items.map((p) => {
          const firstModel = p.models?.[0];
          return (
            <div
              key={p.id}
              className={`group grid ${GRID} items-center gap-2 px-5 py-3 transition-colors hover:bg-zinc-50`}
              style={{ borderTop: "1px solid var(--color-border-soft)" }}
            >
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              <span className="truncate text-sm" style={{ color: "var(--color-ink-soft)" }}>{p.name}</span>
              <span className="truncate text-xs" style={{ color: "var(--color-ink-faint)" }}>{typeLabel(p.type)}</span>
              <span className="truncate font-mono text-xs" style={{ color: "var(--color-ink-faint)" }}>
                {mask(p.api_key_ref)}
              </span>
              <span className="truncate text-xs" style={{ color: "var(--color-ink-faint)" }}>
                {p.base_url || "—"}
              </span>
              <span className="truncate text-xs" style={{ color: "var(--color-ink-faint)" }}>
                {firstModel?.model_name ?? "—"}
                {p.models && p.models.length > 1 && (
                  <span className="ml-1 rounded px-1 text-[10px]" style={{ backgroundColor: "var(--color-surface-alt)" }}>
                    +{p.models.length - 1}
                  </span>
                )}
              </span>
              <RowActionsMenu
                actions={[
                  { label: "编辑", onClick: () => onEdit(p) },
                  {
                    label: "删除",
                    tone: "danger",
                    onClick: () => {
                      if (confirm(`删除 LLM "${p.name}"？\n所有模型将一并删除。`)) deleteMut.mutate(p.id);
                    },
                  },
                ]}
              />
            </div>
          );
        })
      )}
    </div>
  );
}

export default LlmTable;
