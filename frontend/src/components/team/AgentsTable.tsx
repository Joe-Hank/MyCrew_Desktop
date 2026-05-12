import { useAgents, useDeleteAgent, type Agent } from "../../queries/useTeamQuery";
import { useLlmProviders } from "../../queries/useLlmQuery";
import RowActionsMenu from "../common/RowActionsMenu";

const GRID = "grid-cols-[1.4fr_1.1fr_0.8fr_1.2fr_1.4fr_60px]";

function AgentsTable({ onEdit }: { onEdit: (a: Agent) => void }) {
  const { data: agents, isLoading } = useAgents();
  const { data: providers } = useLlmProviders();
  const deleteMut = useDeleteAgent();

  const items = agents ?? [];
  const providerList = (providers as unknown as Array<{ id: string; name: string }>) ?? [];

  function modelLabel(llmId: string | null): string {
    if (!llmId) return "—";
    if (llmId.includes(":")) {
      const [pid, mname] = llmId.split(":");
      const p = providerList.find((x) => x.id === pid);
      return p ? `${p.name} ${mname}` : llmId;
    }
    const p = providerList.find((x) => x.id === llmId);
    return p?.name ?? llmId;
  }

  if (isLoading) {
    return <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>加载中...</div>;
  }

  return (
    <div
      className="overflow-hidden rounded-xl bg-white"
      style={{ border: "1px solid var(--color-border-soft)" }}
    >
      {/* Header */}
      <div
        className={`grid ${GRID} items-center gap-2 px-5 py-3`}
        style={{ borderBottom: "1px solid var(--color-border-soft)" }}
      >
        {["名称", "模型", "思考模式", "工具", "记忆路径", "操作"].map((c) => (
          <span key={c} className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>
            {c}
          </span>
        ))}
      </div>

      {/* Rows */}
      {items.length === 0 ? (
        <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>
          暂无 Agent
        </div>
      ) : (
        items.map((agent) => (
          <div
            key={agent.id}
            className={`group grid ${GRID} items-center gap-2 px-5 py-3 transition-colors hover:bg-zinc-50`}
            style={{ borderTop: "1px solid var(--color-border-soft)" }}
          >
            <div className="flex items-center gap-2.5">
              <span
                className="inline-flex h-7 w-7 items-center justify-center rounded-full"
                style={{ backgroundColor: "var(--color-surface-alt)" }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  style={{ color: "var(--color-ink-muted)" }}>
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
              </span>
              <span className="truncate text-sm" style={{ color: "var(--color-ink-soft)" }}>
                {agent.role}
              </span>
            </div>
            <span className="truncate text-xs" style={{ color: "var(--color-ink-faint)" }}>
              {modelLabel(agent.llm_id)}
            </span>
            <Toggle on={agent.thinking_mode} />
            <span className="truncate text-xs" style={{ color: "var(--color-ink-faint)" }}>
              {agent.tool_ids?.length ? `${agent.tool_ids.length} 个工具` : "—"}
            </span>
            <span
              className="truncate text-xs underline-offset-2 hover:underline"
              style={{ color: "var(--color-ink-faint)" }}
              title={agent.memory_path ?? ""}
            >
              {agent.memory_path || "—"}
            </span>
            <RowActionsMenu
              actions={[
                { label: "编辑", onClick: () => onEdit(agent) },
                {
                  label: "删除",
                  tone: "danger",
                  onClick: () => {
                    if (confirm(`删除 Agent "${agent.role}"？`)) deleteMut.mutate(agent.id);
                  },
                },
              ]}
            />
          </div>
        ))
      )}
    </div>
  );
}

function Toggle({ on }: { on: boolean }) {
  return (
    <span
      className="relative inline-flex h-6 w-11 items-center rounded-full"
      style={{
        backgroundColor: on ? "#10b981" : "var(--color-surface-alt)",
      }}
    >
      <span
        className="absolute h-5 w-5 rounded-full bg-white shadow-sm transition-transform"
        style={{ transform: on ? "translateX(24px)" : "translateX(2px)" }}
      />
    </span>
  );
}

export default AgentsTable;
