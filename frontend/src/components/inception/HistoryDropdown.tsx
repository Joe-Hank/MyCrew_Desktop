import { useEffect, useRef, useState } from "react";
import {
  useInceptionSessions,
  useDeleteInceptionSession,
  useRenameInceptionSession,
  type InceptionSession,
} from "../../queries/useInceptionQuery";
import RowActionsMenu from "../common/RowActionsMenu";

const PAGE_SIZE = 10;

/** Inception 历史会话下拉。从 InceptionDrawer 抽出独立文件。
 *
 *  特性（vs 旧版）：
 *   - 按 last_activity_at 倒序（NULL 退回 created_at）
 *   - 顶部 debounced 搜索框（标题 / 项目名 / 首条用户消息）
 *   - 每条悬浮 ⋯ 菜单：重命名 / 删除（复用 RowActionsMenu）
 *   - inline rename 输入框（Enter 提交，Esc 取消）
 *   - 分页 10/次，"加载更多" 累积
 *   - 内容摘要预览（首条 user 消息，0-80 字）
 *   - 删除当前活跃 session 时通知父组件解绑 activeSessionId
 */
interface Props {
  activeId: string | null;
  onSelect: (id: string) => void;
  onActiveDeleted: () => void; // called when the row being deleted IS the active one
}

function HistoryDropdown({ activeId, onSelect, onActiveDeleted }: Props) {
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [offset, setOffset] = useState(0);

  // Debounce search → query
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(searchInput.trim());
      setOffset(0); // reset pagination on new search
    }, 250);
    return () => clearTimeout(t);
  }, [searchInput]);

  const { data, isLoading } = useInceptionSessions({
    q: debouncedQ,
    limit: offset + PAGE_SIZE, // "load more" approach: ask for everything up to current page top
    offset: 0,
  });
  const deleteMut = useDeleteInceptionSession();
  const renameMut = useRenameInceptionSession();

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const hasMore = items.length < total;

  return (
    <div
      className="absolute right-0 top-11 z-40 w-80 rounded-lg shadow-xl"
      style={{
        backgroundColor: "var(--color-card)",
        border: "1px solid var(--color-border-soft)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 text-xs font-medium"
        style={{
          color: "var(--color-ink-faint)",
          borderBottom: "1px solid var(--color-border-soft)",
        }}
      >
        <span>历史会话</span>
        <span style={{ color: "var(--color-ink-ghost)" }}>{total} 条</span>
      </div>

      {/* Search */}
      <div
        className="px-2 py-2"
        style={{ borderBottom: "1px solid var(--color-border-soft)" }}
      >
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="搜索 名称 / 项目 / 首条消息..."
          className="w-full rounded-md px-2 py-1 text-xs outline-none"
          style={{
            backgroundColor: "var(--color-card-alt)",
            border: "1px solid var(--color-border-soft)",
            color: "var(--color-ink)",
          }}
        />
      </div>

      {/* List */}
      <div className="max-h-96 overflow-auto">
        {isLoading && items.length === 0 ? (
          <div
            className="p-4 text-center text-xs"
            style={{ color: "var(--color-ink-ghost)" }}
          >
            加载中…
          </div>
        ) : items.length === 0 ? (
          <div
            className="p-4 text-center text-xs"
            style={{ color: "var(--color-ink-ghost)" }}
          >
            {debouncedQ ? "无匹配会话" : "暂无会话"}
          </div>
        ) : (
          items.map((s) => (
            <SessionRow
              key={s.id}
              session={s}
              isActive={activeId === s.id}
              onSelect={() => onSelect(s.id)}
              onRename={(title) =>
                renameMut.mutate({ id: s.id, title })
              }
              onDelete={() => {
                if (!confirm(`删除会话 "${s.title_resolved}"？`)) return;
                if (activeId === s.id) onActiveDeleted();
                deleteMut.mutate(s.id);
              }}
            />
          ))
        )}
      </div>

      {/* Pagination */}
      {hasMore && (
        <button
          onClick={() => setOffset((o) => o + PAGE_SIZE)}
          className="block w-full px-3 py-2 text-center text-xs transition-colors hover:bg-zinc-50"
          style={{
            color: "var(--color-ink-faint)",
            borderTop: "1px solid var(--color-border-soft)",
          }}
        >
          加载更多 ({items.length}/{total})
        </button>
      )}
    </div>
  );
}

/** Single session row — title + meta + preview, with inline-edit rename
 *  and a ⋯ menu (portal'd by RowActionsMenu). */
function SessionRow({
  session,
  isActive,
  onSelect,
  onRename,
  onDelete,
}: {
  session: InceptionSession;
  isActive: boolean;
  onSelect: () => void;
  onRename: (newTitle: string) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(session.title_resolved);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setDraftTitle(session.title || session.title_resolved);
      // focus + select after render
      setTimeout(() => {
        inputRef.current?.focus();
        inputRef.current?.select();
      }, 0);
    }
  }, [editing, session.title, session.title_resolved]);

  function commit() {
    const next = draftTitle.trim();
    if (next && next !== (session.title ?? session.title_resolved)) {
      onRename(next);
    }
    setEditing(false);
  }

  const ts = (session.last_activity_at ?? session.created_at ?? "").substring(0, 16);

  return (
    <div
      onClick={editing ? undefined : onSelect}
      className="group flex cursor-pointer flex-col gap-0.5 px-3 py-2 transition-colors hover:bg-zinc-50"
      style={{
        backgroundColor: isActive ? "var(--color-surface-alt)" : "transparent",
        borderBottom: "1px solid var(--color-border-soft)",
      }}
    >
      <div className="flex w-full items-center gap-2">
        {/* Title (or inline-edit input) */}
        {editing ? (
          <input
            ref={inputRef}
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              if (e.key === "Escape") setEditing(false);
            }}
            onClick={(e) => e.stopPropagation()}
            onBlur={commit}
            className="flex-1 rounded px-1 py-0.5 text-xs outline-none"
            style={{
              backgroundColor: "var(--color-card-alt)",
              border: "1px solid var(--color-border-soft)",
              color: "var(--color-ink)",
            }}
          />
        ) : (
          <span
            className="flex-1 truncate text-xs font-medium"
            style={{ color: "var(--color-ink-soft)" }}
            title={session.title_resolved}
          >
            {session.title_resolved}
          </span>
        )}

        {session.is_draft && (
          <span
            className="shrink-0 rounded px-1 text-[9px]"
            style={{
              backgroundColor: "rgba(245, 158, 11, 0.18)",
              color: "#92400e",
            }}
          >
            草稿
          </span>
        )}

        {/* ⋯ menu — appears on hover (group-hover) so the resting row is clean */}
        <div
          className="opacity-0 transition-opacity group-hover:opacity-100"
          onClick={(e) => e.stopPropagation()}
        >
          <RowActionsMenu
            actions={[
              { label: "重命名", onClick: () => setEditing(true) },
              { label: "删除", tone: "danger", onClick: onDelete },
            ]}
          />
        </div>
      </div>

      <div className="flex items-center justify-between gap-2">
        {session.preview && (
          <span
            className="flex-1 truncate text-[11px]"
            style={{ color: "var(--color-ink-faint)" }}
            title={session.preview}
          >
            {session.preview}
          </span>
        )}
        <span
          className="shrink-0 text-[10px]"
          style={{ color: "var(--color-ink-ghost)" }}
        >
          {ts}
        </span>
      </div>
    </div>
  );
}

export default HistoryDropdown;
