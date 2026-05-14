import { useCrews, useDeleteCrew, useAgents, type Crew } from "../../queries/useTeamQuery";
import RowActionsMenu from "../common/RowActionsMenu";

// Mirror AgentsTable / ToolsTable layout: fr ratios for content cols +
// a fixed 60px actions column. Members gets the most fr since it has
// the longest comma-joined content; process matches Agent's toggle col
// width (~0.8fr) so the chip lines up at consistent density across tabs.
const GRID = "grid-cols-[1.4fr_2.5fr_0.8fr_60px]";

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

/** Compact 2-segment toggle: 链式 / 层式, brand-blue highlight on the
 *  active one. Read-only here (clicking does nothing); the editor drawer
 *  is where the user actually picks. Total width ≈ 60px so the grid
 *  column hugs the chip. */
function ProcessToggle({ process }: { process: string }) {
  const isHier = process === "hierarchical";
  const segStyle = (active: boolean): React.CSSProperties => ({
    padding: "1px 6px",
    backgroundColor: active ? "var(--color-brand-500)" : "transparent",
    color: active ? "white" : "var(--color-ink-faint)",
  });
  return (
    <span
      className="inline-flex overflow-hidden rounded text-[11px] font-medium"
      style={{ border: "1px solid var(--color-border-soft)" }}
    >
      <span style={segStyle(!isHier)}>链式</span>
      <span style={segStyle(isHier)}>层式</span>
    </span>
  );
}

export default CrewsTable;
