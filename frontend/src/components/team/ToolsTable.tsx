import { useTools, useDeleteTool, type Tool } from "../../queries/useTeamQuery";
import RowActionsMenu from "../common/RowActionsMenu";

const GRID = "grid-cols-[1fr_2fr_60px]";

function ToolsTable({ onEdit }: { onEdit: (t: Tool) => void }) {
  const { data: tools, isLoading } = useTools();
  const deleteMut = useDeleteTool();

  const items = tools ?? [];

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
        {["名称", "路径", "操作"].map((c) => (
          <span key={c} className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>
            {c}
          </span>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="p-8 text-center text-sm" style={{ color: "var(--color-ink-ghost)" }}>
          暂无工具
        </div>
      ) : (
        items.map((tool) => (
          <div
            key={tool.id}
            className={`group grid ${GRID} items-center gap-2 px-5 py-3 transition-colors hover:bg-zinc-50`}
            style={{ borderTop: "1px solid var(--color-border-soft)" }}
          >
            <span className="truncate text-sm" style={{ color: "var(--color-ink-soft)" }}>
              {tool.name}
            </span>
            <span
              className="truncate text-xs underline-offset-2 hover:underline"
              style={{ color: "var(--color-ink-faint)" }}
              title={tool.script_path ?? ""}
            >
              {tool.script_path || "—"}
            </span>
            <RowActionsMenu
              actions={[
                { label: "编辑", onClick: () => onEdit(tool) },
                {
                  label: "删除",
                  tone: "danger",
                  onClick: () => {
                    if (confirm(`删除工具 "${tool.name}"？`)) deleteMut.mutate(tool.id);
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

export default ToolsTable;
