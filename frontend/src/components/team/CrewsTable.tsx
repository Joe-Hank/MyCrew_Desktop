import { useCrews, useDeleteCrew, useAgents, type Crew } from "../../queries/useTeamQuery";
import RowActionsMenu from "../common/RowActionsMenu";

const GRID = "grid-cols-[1.4fr_2fr_1.2fr_60px]";

function CrewsTable({ onEdit }: { onEdit: (c: Crew) => void }) {
  const { data: crews, isLoading } = useCrews();
  const { data: agents } = useAgents();
  const deleteMut = useDeleteCrew();

  const items = crews ?? [];
  const agentMap = new Map((agents ?? []).map((a) => [a.id, a.role]));

  if (isLoading) {
    return <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>加载中...</div>;
  }

  return (
    <div
      className="overflow-hidden rounded-xl bg-white"
      style={{ border: "1px solid var(--color-border-soft)" }}
    >
      <div
        className={`grid ${GRID} items-center gap-2 px-5 py-3`}
        style={{ borderBottom: "1px solid var(--color-border-soft)" }}
      >
        {["名称", "成员", "过程控制", "操作"].map((c) => (
          <span key={c} className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>
            {c}
          </span>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>
          暂无 Crew
        </div>
      ) : (
        items.map((crew) => (
          <div
            key={crew.id}
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
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </span>
              <span className="truncate text-sm" style={{ color: "var(--color-ink-soft)" }}>
                {crew.name}
              </span>
            </div>
            <span
              className="truncate text-xs"
              style={{ color: "var(--color-ink-faint)" }}
              title={crew.agent_ids.map((id) => agentMap.get(id) ?? id).join(", ")}
            >
              {crew.agent_ids.map((id) => agentMap.get(id) ?? id).join(", ") || "无成员"}
            </span>
            <ProcessToggle process={crew.process} />
            <RowActionsMenu
              actions={[
                { label: "编辑", onClick: () => onEdit(crew) },
                {
                  label: "删除",
                  tone: "danger",
                  onClick: () => {
                    if (confirm(`删除 Crew "${crew.name}"？`)) deleteMut.mutate(crew.id);
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

function ProcessToggle({ process }: { process: string }) {
  const isSequential = process === "sequential";
  return (
    <span
      className="inline-flex items-center rounded-full p-0.5 text-xs"
      style={{ backgroundColor: "var(--color-surface-alt)" }}
    >
      <span
        className="rounded-full px-3 py-1"
        style={{
          backgroundColor: isSequential ? "white" : "transparent",
          color: isSequential ? "var(--color-ink-label)" : "var(--color-ink-faint)",
        }}
      >
        链式
      </span>
      <span
        className="rounded-full px-3 py-1"
        style={{
          backgroundColor: !isSequential ? "white" : "transparent",
          color: !isSequential ? "var(--color-ink-label)" : "var(--color-ink-faint)",
        }}
      >
        层式
      </span>
    </span>
  );
}

export default CrewsTable;
