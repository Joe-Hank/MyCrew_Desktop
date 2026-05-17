import { useEffect, useMemo, useRef, useState } from "react";

import type { PMLogEntry, PMState } from "../../hooks/usePmState";

/** Right-side debug log panel shown while PM v3 is running OR after
 *  it finished (until "保存项目" replaces it with the blueprint editor).
 *
 *  Text-log style per user spec. Phase headers are collapsible; the
 *  current/most-recent phase is auto-expanded. Failed phase highlighted
 *  amber. Payload previews available via "展开" inside each entry. */

const PHASE_LABELS: Record<string, string> = {
  completeness: "完整度判定",
  concept: "Phase 1 · 游戏主策划",
  system_design: "Phase 2 · 系统策划",
  review: "Phase 3 · 审核策划",
  project_mgmt: "Phase 4 · 项目管理",
  // PM v5 (2026-05-17): inserted between project_mgmt and assignment.
  // Decides cross-task C# symbol contract before any Crew runs.
  code_contract: "Phase 5 · 代码契约设计师",
  agent_assignment: "Phase 6 · Agent 指挥员",
  complete: "完成",
};

const PHASE_ORDER = [
  "completeness",
  "concept",
  "system_design",
  "review",
  "project_mgmt",
  "code_contract",
  "agent_assignment",
  "complete",
];

interface Props {
  state: PMState;
}

function PMDebugLog({ state }: Props) {
  // Group entries by phase
  const grouped = useMemo(() => {
    const m = new Map<string, PMLogEntry[]>();
    for (const e of state.debug_log) {
      if (!m.has(e.phase)) m.set(e.phase, []);
      m.get(e.phase)!.push(e);
    }
    return m;
  }, [state.debug_log]);

  // Track which phases the user has manually toggled
  const [manuallyToggled, setManuallyToggled] = useState<Record<string, boolean>>({});

  function isExpanded(phase: string): boolean {
    if (manuallyToggled[phase] !== undefined) return manuallyToggled[phase];
    // Default: current phase + failed phase expanded; others collapsed
    return (
      phase === state.current_phase ||
      phase === state.failed_phase ||
      state.status === "running"  // expand all while running for visibility
    );
  }

  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [state.debug_log.length]);

  return (
    <div className="flex h-full flex-col">
      <PMStatusHeader state={state} />
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto pr-1"
      >
        {/* Always render every phase as a row — pending phases get a
            `·` glyph, current gets ▶, completed ✓, failed ⚠️. Lets
            the user see the whole 5-phase pipeline up-front (incl.
            the ones that haven't fired yet) rather than only the
            phases that have produced log entries. */}
        {PHASE_ORDER.map((phase) => {
          const entries = grouped.get(phase) ?? [];
          const isFailed = phase === state.failed_phase;
          const isCurrent = phase === state.current_phase;
          return (
            <PhaseSection
              key={phase}
              phase={phase}
              entries={entries}
              expanded={isExpanded(phase) && entries.length > 0}
              isFailed={isFailed}
              isCurrent={isCurrent}
              onToggle={() =>
                setManuallyToggled((prev) => ({
                  ...prev,
                  [phase]: !isExpanded(phase),
                }))
              }
            />
          );
        })}
      </div>
    </div>
  );
}

function PMStatusHeader({ state }: { state: PMState }) {
  const label = (() => {
    if (state.status === "running") return "PM 工作流运行中…";
    if (state.status === "ready") return "✓ 草稿就绪";
    if (state.status === "failed") return "⚠️ 工作流失败";
    if (state.status === "cancelled") return "⏹ 已取消";
    return "等待启动";
  })();
  const color = (() => {
    if (state.status === "ready") return "#10b981";
    if (state.status === "failed") return "#f59e0b";
    if (state.status === "cancelled") return "var(--color-ink-ghost)";
    return "var(--color-brand-500)";
  })();
  return (
    <div
      className="mb-2 flex items-center gap-2 px-3 py-2 text-sm font-medium"
      style={{
        borderBottom: "1px solid var(--color-border-soft)",
        color: "var(--color-ink-soft)",
      }}
    >
      {state.status === "running" && (
        <span className="inline-flex h-2 w-2 animate-pulse rounded-full"
              style={{ backgroundColor: color }} />
      )}
      <span style={{ color }}>{label}</span>
      {state.completeness && (
        <span
          className="ml-2 rounded-md px-2 py-0.5 text-[10px]"
          style={{
            backgroundColor: "var(--color-surface-alt)",
            color: "var(--color-ink-muted)",
          }}
        >
          {state.completeness}
        </span>
      )}
    </div>
  );
}

function PhaseSection({
  phase,
  entries,
  expanded,
  isFailed,
  isCurrent,
  onToggle,
}: {
  phase: string;
  entries: PMLogEntry[];
  expanded: boolean;
  isFailed: boolean;
  isCurrent: boolean;
  onToggle: () => void;
}) {
  const label = PHASE_LABELS[phase] ?? phase;
  const done = entries.some((e) => e.status === "phase_completed");
  const pending = entries.length === 0 && !isCurrent && !isFailed && !done;
  const glyph = isFailed
    ? "⚠️"
    : done
      ? "✓"
      : isCurrent
        ? "▶"
        : pending
          ? "○"
          : "·";
  const bg = isFailed
    ? "rgba(245, 158, 11, 0.08)"
    : isCurrent
      ? "rgba(12, 140, 233, 0.06)"
      : "transparent";
  // Pending phases (no entries yet) read in ink-ghost so they recede
  // visually relative to running / completed ones.
  const textColor = pending
    ? "var(--color-ink-ghost)"
    : "var(--color-ink-soft)";
  const countLabel = entries.length > 0 ? `${entries.length} 条` : "等待";
  const toggleable = entries.length > 0;
  return (
    <div
      className="mb-2 rounded-md"
      style={{
        backgroundColor: bg,
        border: isFailed
          ? "1px solid rgba(245, 158, 11, 0.4)"
          : "1px solid transparent",
      }}
    >
      <button
        onClick={toggleable ? onToggle : undefined}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] font-medium"
        style={{
          color: textColor,
          cursor: toggleable ? "pointer" : "default",
        }}
      >
        <span style={{ width: "14px" }}>{glyph}</span>
        <span className="flex-1">{label}</span>
        <span
          className="text-[10px]"
          style={{ color: "var(--color-ink-ghost)" }}
        >
          {countLabel}
        </span>
        <span
          className="text-[10px]"
          style={{ color: "var(--color-ink-ghost)" }}
        >
          {toggleable ? (expanded ? "▾" : "▸") : ""}
        </span>
      </button>
      {expanded && entries.length > 0 && (
        <div className="px-3 pb-2 pl-7">
          {entries.map((e, i) => (
            <LogEntry key={`${e.ts}_${i}`} entry={e} />
          ))}
        </div>
      )}
    </div>
  );
}

function LogEntry({ entry }: { entry: PMLogEntry }) {
  const [open, setOpen] = useState(false);
  const ts = entry.ts.slice(11, 19);  // HH:MM:SS
  const hasPayload = entry.payload_preview != null;
  const hasDetail = entry.detail != null;
  const hasError = !!entry.error;
  const expandable = hasPayload || hasDetail || hasError;
  const statusGlyph = (() => {
    if (entry.status === "phase_failed") return "✗";
    if (entry.status === "phase_completed") return "✓";
    if (entry.status === "retry") return "↻";
    if (entry.status === "tool_call") return "⚙";
    return "▸";
  })();
  return (
    <div className="py-1 text-[11px]" style={{ color: "var(--color-ink-muted)" }}>
      <div className="flex items-start gap-2">
        <span
          className="shrink-0 font-mono"
          style={{ color: "var(--color-ink-ghost)" }}
        >
          {ts}
        </span>
        <span className="shrink-0 w-3 text-center">{statusGlyph}</span>
        <span className="flex-1 break-words">{entry.message}</span>
        {expandable && (
          <button
            onClick={() => setOpen((v) => !v)}
            className="shrink-0 text-[10px] underline-offset-2 hover:underline"
            style={{ color: "var(--color-ink-ghost)" }}
          >
            {open ? "收起" : "展开"}
          </button>
        )}
      </div>
      {open && expandable && (
        <div
          className="mt-1 ml-12 rounded p-2 font-mono text-[10px]"
          style={{
            backgroundColor: "var(--color-surface-alt)",
            color: "var(--color-ink-faint)",
          }}
        >
          {hasError && (
            <div style={{ color: "#f59e0b" }} className="mb-1">
              错误：{entry.error}
            </div>
          )}
          {hasDetail && (
            <pre className="whitespace-pre-wrap">{entry.detail}</pre>
          )}
          {hasPayload && (
            <pre className="whitespace-pre-wrap">
              {typeof entry.payload_preview === "string"
                ? entry.payload_preview
                : JSON.stringify(entry.payload_preview, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export default PMDebugLog;
