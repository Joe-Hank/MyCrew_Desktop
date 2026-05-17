import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useEvent, useAnyEvent } from "../../hooks/useEvent";
import { usePrefsStore, type LogTab } from "../../stores/usePrefsStore";
import { apiFetch } from "../../net/api";
import type { WsMessage } from "../../net/ws";

const TABS: LogTab[] = ["后端日志", "Agent 输出", "LLM 调用"];
const MAX_RENDER = 1000;  // hard cap on DOM rows for perf; raise if needed
const BUFFER_LIMIT = 5000;  // in-memory cap matching backend's

// ── Types ──────────────────────────────────────────────────────────

interface BackendLog {
  ts: string;
  level: string;
  source: string;
  event: string;
  message: string;
  fields: Record<string, unknown>;
  project_id?: string | null;
  task_id?: string | null;
}

interface AgentLog {
  ts: string;
  type: string;
  message: string;
}

// ── T2: LLM call pairing types ─────────────────────────────────────

interface LLMMessagePreview {
  role: string;
  content: string;
}

interface LLMCallEntry {
  call_id: string;
  ts_request: string;
  ts_response?: string;
  provider_id: string;
  model: string;
  // Request side
  thinking_mode?: boolean;
  json_mode?: boolean;
  max_tokens?: number | null;
  temperature?: number | null;
  messages_preview?: LLMMessagePreview[];
  messages_count?: number;
  // Response side
  status: "pending" | "ok" | "error";
  tokens?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  latency_ms?: number;
  text_preview?: string;
  error?: string;
}

// ── Agent-tab summary builder (kept from prior LogDrawer) ──────────

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}

function summariseAgentPayload(
  type: string, payload: Record<string, unknown> | undefined,
): string {
  if (!payload) return "";
  if (typeof payload.message === "string") return payload.message;
  if (type === "agent.output") {
    const role = typeof payload.agent_role === "string" ? payload.agent_role : "Agent";
    const step = payload.step != null ? `#${payload.step} ` : "";
    const tid = typeof payload.task_id === "string" ? ` · tid=${payload.task_id.slice(-6)}` : "";
    const text = typeof payload.text === "string" ? truncate(payload.text, 140) : "";
    return `[${role}] ${step}${text}${tid}`;
  }
  if (typeof payload.task_id === "string") return `tid=${payload.task_id.slice(-6)}`;
  try { return truncate(JSON.stringify(payload), 120); } catch { return type; }
}

const AGENT_TAB_EVENTS = new Set([
  "agent.output", "task.started", "task.completed", "task.failed",
  "task.paused", "task.blocked", "task.validation_failed",
  "task.sub_step",
]);

// ── Level styling ──────────────────────────────────────────────────

function levelColor(level: string): string {
  const l = level.toLowerCase();
  if (l === "error") return "#dc2626";
  if (l === "warning" || l === "warn") return "#d97706";
  if (l === "debug") return "var(--color-ink-ghost)";
  return "var(--color-ink-soft)";
}

/** Render an ISO timestamp (backend emits UTC via structlog
 *  TimeStamper) as local hh:mm:ss. The previous `ts.substring(11, 19)`
 *  rendered the UTC hours literally, which shows as 8 hours behind
 *  Beijing wall-clock time and confuses users who expect the LogDrawer
 *  to match what their system clock says. */
function localHMS(iso: string | undefined | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    // Malformed / non-ISO — fall back to the raw substring so we don't
    // drop information on the floor.
    return typeof iso === "string" ? iso.substring(11, 19) : "";
  }
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

// ── Main component ─────────────────────────────────────────────────

function LogDrawer() {
  const expanded = usePrefsStore((s) => s.logDrawerExpanded);
  const setExpanded = usePrefsStore((s) => s.setLogDrawerExpanded);
  const activeTab = usePrefsStore((s) => s.logDrawerActiveTab);
  const setActiveTab = usePrefsStore((s) => s.setLogDrawerActiveTab);
  const height = usePrefsStore((s) => s.logDrawerHeight);
  const setHeight = usePrefsStore((s) => s.setLogDrawerHeight);
  const filters = usePrefsStore((s) => s.logDrawerFilters);
  const setFilters = usePrefsStore((s) => s.setLogDrawerFilters);

  // ── Backend log stream (T1) ──────────────────────────────────────
  const [backendLogs, setBackendLogs] = useState<BackendLog[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  // Mount-time replay so the panel is non-empty even after page refresh
  // / new session. Backend buffer keeps 2000 latest records.
  useEffect(() => {
    if (!expanded) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch<{
          logs: BackendLog[]; buffer_size: number;
        }>("/logs?limit=500");
        if (cancelled || !res.ok || !res.data) return;
        // Backend returns newest-first; we store oldest-first for
        // append-friendly state updates, then reverse for display.
        setBackendLogs(res.data.logs.slice().reverse());
      } catch {
        // Network blip — leave existing state alone
      }
      try {
        const r = await apiFetch<{ sources: string[] }>("/logs/sources");
        if (!cancelled && r.ok && r.data) setSources(r.data.sources);
      } catch { /* noop */ }
    })();
    return () => { cancelled = true; };
  }, [expanded]);

  // Live append via new WS log.line channel (tap_processor)
  useEvent("log.line", useCallback((msg: WsMessage) => {
    const entry = msg.payload as unknown as BackendLog;
    if (!entry || typeof entry.event !== "string") return;
    setBackendLogs((prev) => {
      const next = prev.length >= BUFFER_LIMIT
        ? prev.slice(prev.length - BUFFER_LIMIT + 1)
        : prev.slice();
      next.push(entry);
      return next;
    });
    // Keep source list growing as new prefixes show up
    if (entry.source && !sources.includes(entry.source)) {
      setSources((prev) => prev.includes(entry.source!)
        ? prev : [...prev, entry.source!].sort());
    }
  }, [sources]));

  // ── T2: LLM call pairing ────────────────────────────────────────
  // llm.call.detail fires twice per LLM call (request + response/error).
  // Pair by call_id to render one row per call with timing + tokens.
  const [llmCalls, setLlmCalls] = useState<LLMCallEntry[]>([]);
  useEvent("llm.call.detail", useCallback((msg: WsMessage) => {
    const p = msg.payload as Record<string, unknown>;
    const callId = typeof p.call_id === "string" ? p.call_id : "";
    const phase = typeof p.phase === "string" ? p.phase : "";
    if (!callId || !phase) return;
    setLlmCalls((prev) => {
      // Find existing row by call_id
      const idx = prev.findIndex((c) => c.call_id === callId);
      const next = prev.slice();
      if (phase === "request") {
        const entry: LLMCallEntry = {
          call_id: callId,
          ts_request: msg.ts,
          provider_id: String(p.provider_id ?? ""),
          model: String(p.model ?? ""),
          thinking_mode: Boolean(p.thinking_mode),
          json_mode: Boolean(p.json_mode),
          max_tokens: (p.max_tokens as number | null) ?? null,
          temperature: (p.temperature as number | null) ?? null,
          messages_preview: (p.messages_preview as LLMMessagePreview[]) ?? [],
          messages_count: (p.messages_count as number) ?? 0,
          status: "pending",
        };
        if (idx >= 0) {
          next[idx] = { ...next[idx], ...entry };
        } else {
          next.push(entry);
          // Cap at 500 calls
          if (next.length > 500) next.shift();
        }
      } else if (phase === "response" || phase === "error") {
        const update: Partial<LLMCallEntry> = {
          ts_response: msg.ts,
          status: phase === "response" ? "ok" : "error",
          tokens: (p.tokens as number) ?? 0,
          prompt_tokens: (p.prompt_tokens as number) ?? 0,
          completion_tokens: (p.completion_tokens as number) ?? 0,
          latency_ms: (p.latency_ms as number) ?? 0,
          text_preview: typeof p.text_preview === "string"
            ? p.text_preview : undefined,
          error: typeof p.error === "string" ? p.error : undefined,
        };
        if (idx >= 0) {
          // Required fields already exist on next[idx]; cast the merge
          // result to satisfy strictPropertyInitialization for the
          // spread.
          next[idx] = Object.assign({}, next[idx], update) as LLMCallEntry;
        } else {
          // Response without prior request — shouldn't happen unless
          // we missed the request event. Synthesize a row.
          const synth: LLMCallEntry = {
            call_id: callId,
            ts_request: msg.ts,
            provider_id: String(p.provider_id ?? ""),
            model: String(p.model ?? ""),
            status: phase === "response" ? "ok" : "error",
          };
          next.push(Object.assign(synth, update));
        }
      }
      return next;
    });
  }, []));

  // ── Agent-tab stream (legacy) ────────────────────────────────────
  const [agentLogs, setAgentLogs] = useState<AgentLog[]>([]);
  useAnyEvent(useCallback((msg: WsMessage) => {
    if (!AGENT_TAB_EVENTS.has(msg.type)) return;
    const entry: AgentLog = {
      ts: msg.ts,
      type: msg.type,
      message: summariseAgentPayload(
        msg.type, msg.payload as Record<string, unknown>,
      ),
    };
    setAgentLogs((prev) => {
      const next = prev.length >= 500 ? prev.slice(prev.length - 499) : prev.slice();
      next.push(entry);
      return next;
    });
  }, []));

  // ── Filter the backend-tab rows by user-selected criteria ────────
  const filteredBackend = useMemo(() => {
    if (activeTab !== "后端日志") return [];
    let rows = backendLogs;
    if (filters.level) {
      const wanted = filters.level === "warning" ? "warning" : filters.level;
      rows = rows.filter((r) => r.level.toLowerCase() === wanted);
    }
    if (filters.source) {
      rows = rows.filter((r) => r.source === filters.source);
    }
    if (filters.query) {
      const q = filters.query.toLowerCase();
      rows = rows.filter((r) =>
        r.event.toLowerCase().includes(q)
        || (r.project_id ?? "").toLowerCase().includes(q)
        || (r.task_id ?? "").toLowerCase().includes(q)
        || JSON.stringify(r.fields).toLowerCase().includes(q),
      );
    }
    return rows;
  }, [activeTab, backendLogs, filters]);

  // ── Drag-to-resize handle ────────────────────────────────────────
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);
  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    dragRef.current = { startY: e.clientY, startH: height };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }
  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return;
    // Drawer grows DOWNward into the screen, so dragging UP increases h.
    const dy = dragRef.current.startY - e.clientY;
    setHeight(dragRef.current.startH + dy);
  }
  function onPointerUp(e: React.PointerEvent<HTMLDivElement>) {
    dragRef.current = null;
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch { /* noop */ }
  }

  // ── Auto-scroll: pin to bottom unless user scrolled away ─────────
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);
  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }
  useEffect(() => {
    if (!expanded || !pinnedToBottom.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [filteredBackend, agentLogs, expanded]);

  if (!expanded) {
    return (
      <div
        onClick={() => setExpanded(true)}
        className="flex h-7 cursor-pointer select-none items-center justify-between px-3 text-xs"
        style={{
          backgroundColor: "var(--color-card)",
          color: "var(--color-ink-ghost)",
          borderTop: "1px solid var(--color-border-strong)",
        }}
      >
        <span className="font-mono">&gt;_ 日志</span>
        <span className="text-[10px]">{backendLogs.length} 条 · 点击展开</span>
      </div>
    );
  }

  return (
    <div
      className="relative flex flex-col"
      style={{
        height,
        backgroundColor: "var(--color-card)",
        borderTop: "1px solid var(--color-border-strong)",
      }}
    >
      {/* Drag handle — 4px tall strip on the top edge */}
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        className="absolute left-0 right-0 top-0 z-10 h-1 cursor-row-resize hover:bg-current"
        style={{
          touchAction: "none",
          color: "var(--color-brand-500)",
        }}
        title="拖动调整高度"
      />

      {/* Header: tabs + filters + collapse */}
      <div
        className="flex flex-shrink-0 items-center gap-2 px-2 pt-1.5"
        style={{ borderBottom: "1px solid var(--color-border-soft)" }}
      >
        <div className="flex">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className="px-3 py-1 text-xs transition-colors"
              style={{
                color: activeTab === tab
                  ? "var(--color-ink-label)" : "var(--color-ink-ghost)",
                borderBottom: activeTab === tab
                  ? "2px solid var(--color-brand-500)"
                  : "2px solid transparent",
                fontWeight: activeTab === tab ? 500 : 400,
              }}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Filters only meaningful for 后端日志 tab */}
        {activeTab === "后端日志" && (
          <div className="ml-2 flex items-center gap-1.5 text-[11px]">
            <select
              value={filters.level}
              onChange={(e) => setFilters({ level: e.target.value as "" | "debug" | "info" | "warning" | "error" })}
              className="rounded px-1 py-0.5"
              style={{
                backgroundColor: "var(--color-card-alt)",
                border: "1px solid var(--color-border-soft)",
                color: "var(--color-ink-soft)",
              }}
              title="按 level 过滤"
            >
              <option value="">— level —</option>
              <option value="debug">debug</option>
              <option value="info">info</option>
              <option value="warning">warn</option>
              <option value="error">error</option>
            </select>
            <select
              value={filters.source}
              onChange={(e) => setFilters({ source: e.target.value })}
              className="rounded px-1 py-0.5"
              style={{
                backgroundColor: "var(--color-card-alt)",
                border: "1px solid var(--color-border-soft)",
                color: "var(--color-ink-soft)",
                maxWidth: "120px",
              }}
              title="按 source 前缀过滤"
            >
              <option value="">— source —</option>
              {sources.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <input
              value={filters.query}
              onChange={(e) => setFilters({ query: e.target.value })}
              placeholder="搜索 event / pid / tid / fields"
              className="rounded px-1.5 py-0.5"
              style={{
                backgroundColor: "var(--color-card-alt)",
                border: "1px solid var(--color-border-soft)",
                color: "var(--color-ink-soft)",
                minWidth: "180px",
              }}
            />
            {(filters.level || filters.source || filters.query) && (
              <button
                onClick={() => setFilters({ level: "", source: "", query: "" })}
                className="text-[10px] underline hover:opacity-70"
                style={{ color: "var(--color-ink-ghost)" }}
              >
                清空
              </button>
            )}
          </div>
        )}

        <span
          className="ml-auto text-[10px]"
          style={{ color: "var(--color-ink-ghost)" }}
        >
          {activeTab === "后端日志"
            ? `${filteredBackend.length}/${backendLogs.length}`
            : activeTab === "Agent 输出"
              ? `${agentLogs.length}`
              : `${llmCalls.length}`}
        </span>
        <button
          onClick={() => setExpanded(false)}
          className="px-1 py-0.5 text-base"
          style={{ color: "var(--color-ink-ghost)" }}
          title="收起"
        >
          ▽
        </button>
      </div>

      {/* Body */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 overflow-auto px-3 py-1 font-mono text-[11px]"
        style={{ color: "var(--color-ink-soft)" }}
      >
        {activeTab === "后端日志" && (
          <BackendLogs rows={filteredBackend} />
        )}
        {activeTab === "Agent 输出" && (
          <AgentLogs rows={agentLogs} />
        )}
        {activeTab === "LLM 调用" && (
          <LLMCalls rows={llmCalls} />
        )}
      </div>
    </div>
  );
}

function BackendLogs({ rows }: { rows: BackendLog[] }) {
  if (rows.length === 0) {
    return (
      <div style={{ color: "var(--color-ink-ghost)" }}>
        &gt;_ 后端尚未生成日志（或被过滤）...
      </div>
    );
  }
  // Cap render to most recent MAX_RENDER for perf — full data still in
  // state, can be filtered down to fit if user wants older entries.
  const truncated = rows.length > MAX_RENDER;
  const visible = truncated ? rows.slice(rows.length - MAX_RENDER) : rows;
  return (
    <>
      {truncated && (
        <div
          className="mb-1 italic"
          style={{ color: "var(--color-ink-ghost)" }}
        >
          (前 {rows.length - MAX_RENDER} 条因渲染上限未显示，可缩小过滤范围查看)
        </div>
      )}
      {visible.map((r, i) => (
        <div key={i} className="leading-5">
          <span style={{ color: "var(--color-ink-ghost)" }}>
            {localHMS(r.ts)}
          </span>{" "}
          <span style={{
            color: levelColor(r.level),
            fontWeight: r.level === "warning" || r.level === "error" ? 600 : 400,
          }}>
            {r.level.padEnd(5).toUpperCase()}
          </span>{" "}
          <span style={{ color: "var(--color-brand-500)" }}>{r.event}</span>
          {Object.keys(r.fields).length > 0 && (
            <span style={{ color: "var(--color-ink-faint)" }}>
              {" "}{fieldsPreview(r.fields)}
            </span>
          )}
        </div>
      ))}
    </>
  );
}

function fieldsPreview(fields: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(fields)) {
    if (parts.length >= 6) { parts.push("…"); break; }
    parts.push(`${k}=${truncate(String(v), 60)}`);
  }
  return parts.join(" ");
}

function AgentLogs({ rows }: { rows: AgentLog[] }) {
  if (rows.length === 0) {
    return (
      <div style={{ color: "var(--color-ink-ghost)" }}>
        &gt;_ Agent 输出会在任务运行时出现这里...
      </div>
    );
  }
  return (
    <>
      {rows.map((r, i) => (
        <div key={i} className="leading-5">
          <span style={{ color: "var(--color-ink-ghost)" }}>
            {localHMS(r.ts)}
          </span>{" "}
          <span style={{ color: "var(--color-brand-500)" }}>[{r.type}]</span>{" "}
          {r.message}
        </div>
      ))}
    </>
  );
}

function LLMCalls({ rows }: { rows: LLMCallEntry[] }) {
  if (rows.length === 0) {
    return (
      <div style={{ color: "var(--color-ink-ghost)" }}>
        &gt;_ 等首次 LLM 调用 — gateway.chat 时这里会出现 request/response 配对...
      </div>
    );
  }
  // Show newest at the bottom (matches scroll-pin behavior of other tabs)
  return (
    <div className="flex flex-col gap-1">
      {rows.map((c) => (
        <LLMCallRow key={c.call_id} call={c} />
      ))}
    </div>
  );
}

function LLMCallRow({ call }: { call: LLMCallEntry }) {
  const [open, setOpen] = useState(false);
  const statusColor =
    call.status === "ok" ? "#10b981"
    : call.status === "error" ? "#dc2626"
    : "var(--color-ink-ghost)";
  const statusGlyph =
    call.status === "ok" ? "✓"
    : call.status === "error" ? "✗"
    : "▶";
  return (
    <div
      className="rounded px-2 py-1"
      style={{
        backgroundColor: open ? "var(--color-card-alt)" : "transparent",
        border: open
          ? "1px solid var(--color-border-soft)"
          : "1px solid transparent",
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-baseline gap-2 text-left text-[11px]"
      >
        <span
          className="shrink-0 font-mono"
          style={{ color: "var(--color-ink-ghost)" }}
        >
          {localHMS(call.ts_request)}
        </span>
        <span className="shrink-0" style={{ color: statusColor }}>
          {statusGlyph}
        </span>
        <span
          className="shrink-0 font-mono"
          style={{ color: "var(--color-ink-faint)" }}
        >
          {call.model || call.provider_id.slice(-12)}
        </span>
        {call.thinking_mode && (
          <span className="shrink-0 text-[9px]" style={{ color: "#6366f1" }}>
            think
          </span>
        )}
        {call.json_mode && (
          <span className="shrink-0 text-[9px]" style={{ color: "#a855f7" }}>
            json
          </span>
        )}
        <span
          className="shrink-0 font-mono tabular-nums"
          style={{ color: "var(--color-ink-soft)" }}
        >
          {call.tokens != null && call.tokens > 0
            ? `${call.tokens} tok`
            : (call.status === "pending" ? "…" : "?")}
        </span>
        <span
          className="shrink-0 font-mono tabular-nums"
          style={{ color: "var(--color-ink-faint)" }}
        >
          {call.latency_ms != null && call.latency_ms > 0
            ? `${call.latency_ms}ms`
            : ""}
        </span>
        <span className="ml-auto text-[10px]" style={{ color: "var(--color-ink-ghost)" }}>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="mt-1.5 pl-6 text-[11px]">
          {call.error && (
            <div
              className="mb-1 rounded p-1.5"
              style={{
                backgroundColor: "rgba(220, 38, 38, 0.08)",
                color: "#b91c1c",
              }}
            >
              <strong>error:</strong> {call.error}
            </div>
          )}
          <div className="mb-2 text-[10px]" style={{ color: "var(--color-ink-ghost)" }}>
            call_id={call.call_id} · prompt={call.prompt_tokens ?? 0}{" "}
            · completion={call.completion_tokens ?? 0}
            {call.max_tokens ? ` · max_tokens=${call.max_tokens}` : ""}
            {call.temperature != null ? ` · temp=${call.temperature}` : ""}
            {call.messages_count != null ? ` · msgs=${call.messages_count}` : ""}
          </div>
          {call.messages_preview && call.messages_preview.length > 0 && (
            <details className="mb-1.5">
              <summary
                className="cursor-pointer select-none text-[10px]"
                style={{ color: "var(--color-ink-ghost)" }}
              >
                请求 messages ({call.messages_preview.length})
              </summary>
              <div className="mt-1 flex flex-col gap-1">
                {call.messages_preview.map((m, i) => (
                  <div
                    key={i}
                    className="rounded p-1.5"
                    style={{
                      backgroundColor: "var(--color-surface-alt)",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    <div
                      className="mb-0.5 text-[9px] uppercase"
                      style={{ color: "var(--color-ink-faint)" }}
                    >
                      {m.role}
                    </div>
                    <div style={{ color: "var(--color-ink-soft)" }}>
                      {m.content}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}
          {call.text_preview && (
            <details open>
              <summary
                className="cursor-pointer select-none text-[10px]"
                style={{ color: "var(--color-ink-ghost)" }}
              >
                响应 text
              </summary>
              <div
                className="mt-1 rounded p-1.5"
                style={{
                  backgroundColor: "var(--color-surface-alt)",
                  color: "var(--color-ink-soft)",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {call.text_preview}
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

export default LogDrawer;
