import { useState, useRef, useEffect, useCallback } from "react";
import { useInceptionStore } from "../../stores/useInceptionStore";
import {
  useInceptionSession,
  useInceptionSessions,
  useCreateInceptionSession,
  useStreamInceptionMessage,
  useSendInceptionMessage,
  useFinalizeInception,
  type Blueprint,
  type InceptionSession,
} from "../../queries/useInceptionQuery";
import { useLlmProviders } from "../../queries/useLlmQuery";
import { useEvent } from "../../hooks/useEvent";
import TaskBlueprintEditor from "./TaskBlueprintEditor";

function InceptionDrawer() {
  const {
    drawerOpen,
    closeDrawer,
    activeSessionId,
    setActiveSession,
    draftBlueprint,
    setDraftBlueprint,
  } = useInceptionStore();
  const { data: session } = useInceptionSession(activeSessionId);
  const { data: providers } = useLlmProviders();
  const createSession = useCreateInceptionSession();
  const streamMessage = useStreamInceptionMessage();
  const sendMessage = useSendInceptionMessage();  // non-streaming fallback (used by Re-evaluate)
  const finalize = useFinalizeInception();

  const [input, setInput] = useState("");
  const [selectedLlm, setSelectedLlm] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [thinking, setThinking] = useState(false);
  const [reEvaluating, setReEvaluating] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  // Streaming assistant text accumulated from inception.delta WS events.
  // Reset on each new send; cleared when the final inception.message arrives.
  const [streamingText, setStreamingText] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const handleBlueprintEvent = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      const bp = msg.payload.blueprint as Blueprint | undefined;
      if (bp && msg.payload.session_id === activeSessionId) {
        setDraftBlueprint(bp);
      }
    },
    [activeSessionId, setDraftBlueprint],
  );

  useEvent("inception.tasks_drafted", handleBlueprintEvent);

  // Listen for streamed LLM tokens — append each delta to the streamingText
  // buffer, scoped to the current session.
  const handleDelta = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      const text = (msg.payload.text as string) ?? "";
      if (text) setStreamingText((prev) => prev + text);
    },
    [activeSessionId],
  );
  useEvent("inception.delta", handleDelta);

  // When the final assistant message arrives, clear the streaming buffer
  // (the real message is already in the cache via mutation onSuccess).
  const handleFullMessage = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      if (msg.payload.role === "assistant") setStreamingText("");
    },
    [activeSessionId],
  );
  useEvent("inception.message", handleFullMessage);

  // Reset streaming buffer when switching sessions
  useEffect(() => {
    setStreamingText("");
  }, [activeSessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages, streamingText]);

  if (!drawerOpen) return null;

  const providerList = (providers as unknown as Array<{ id: string; name: string; models?: Array<{ model_name: string }> }>) ?? [];
  const currentProvider = providerList.find((p) => p.id === selectedLlm);
  const modelOptions = currentProvider?.models ?? [];

  async function ensureSession(): Promise<string | null> {
    if (activeSessionId) return activeSessionId;
    if (!selectedLlm) return null;
    const fullLlmId = selectedModel ? `${selectedLlm}:${selectedModel}` : selectedLlm;
    const res = await createSession.mutateAsync({
      llm_id: fullLlmId,
      thinking_mode: thinking,
    });
    if (res.ok && res.data) {
      const id = (res.data as { id: string }).id;
      setActiveSession(id);
      return id;
    }
    return null;
  }

  async function handleSend() {
    const content = input.trim();
    if (!content) return;
    const sid = await ensureSession();
    if (!sid) return;
    setInput("");
    setStreamingText("");  // reset before new stream
    await streamMessage.mutateAsync({ sessionId: sid, content });
  }

  async function handleFinalize() {
    if (!activeSessionId) return;
    await finalize.mutateAsync({
      sessionId: activeSessionId,
      blueprint: draftBlueprint ?? undefined,
    });
    closeDrawer();
  }

  async function handleReEvaluate() {
    if (!activeSessionId || !draftBlueprint) return;
    setReEvaluating(true);
    try {
      await sendMessage.mutateAsync({
        sessionId: activeSessionId,
        content: `请重新评估以下任务架构的 execution_kind 选择（sequential/crew/flow），并优化任务拆分：\n${JSON.stringify(draftBlueprint, null, 2)}`,
      });
    } finally {
      setReEvaluating(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleNewSession() {
    setActiveSession(null);
    setDraftBlueprint(null);
    setHistoryOpen(false);
  }

  const messages = session?.messages ?? [];

  return (
    <div
      className="fixed inset-0 z-30 flex"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.25)" }}
    >
      {/* Spacer for sidebar */}
      <div className="w-[110px] shrink-0" onClick={closeDrawer} role="presentation" />

      {/* Main overlay area */}
      <div
        className="flex flex-1 flex-col"
        style={{ backgroundColor: "var(--color-surface)" }}
      >
        {/* Top toolbar */}
        <div
          className="flex items-center gap-3 px-5 py-3"
          style={{ borderBottom: "1px solid var(--color-border-soft)", backgroundColor: "var(--color-card)" }}
        >
          {/* LLM picker */}
          <select
            value={selectedLlm}
            onChange={(e) => {
              setSelectedLlm(e.target.value);
              setSelectedModel("");
            }}
            disabled={!!activeSessionId}
            className="rounded-md bg-white px-3 py-1.5 text-sm outline-none disabled:opacity-60"
            style={{ border: "1px solid var(--color-border-soft)" }}
          >
            <option value="">— LLM —</option>
            {providerList.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          {/* Model picker */}
          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={!selectedLlm || !!activeSessionId}
            className="rounded-md bg-white px-3 py-1.5 text-sm outline-none disabled:opacity-60"
            style={{ border: "1px solid var(--color-border-soft)" }}
          >
            <option value="">— 模型 —</option>
            {modelOptions.map((m) => (
              <option key={m.model_name} value={m.model_name}>{m.model_name}</option>
            ))}
          </select>

          {/* Thinking toggle */}
          <div className="flex items-center gap-2 text-sm" style={{ color: "var(--color-ink-label)" }}>
            <span>思考</span>
            <button
              onClick={() => !activeSessionId && setThinking(!thinking)}
              disabled={!!activeSessionId}
              className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-60"
              style={{ backgroundColor: thinking ? "#10b981" : "var(--color-surface-alt)" }}
            >
              <span
                className="absolute h-4 w-4 rounded-full bg-white shadow-sm transition-transform"
                style={{ transform: thinking ? "translateX(18px)" : "translateX(2px)" }}
              />
            </button>
          </div>

          <div className="ml-auto flex items-center gap-2">
            {/* History button */}
            <div className="relative">
              <button
                onClick={() => setHistoryOpen((v) => !v)}
                className="flex h-9 w-9 items-center justify-center rounded-md bg-white transition-colors hover:bg-zinc-50"
                style={{ border: "1px solid var(--color-border-soft)", color: "var(--color-ink-muted)" }}
                title="历史会话"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              </button>
              {historyOpen && (
                <HistoryDropdown
                  activeId={activeSessionId}
                  onSelect={(id) => {
                    setActiveSession(id);
                    setDraftBlueprint(null);
                    setHistoryOpen(false);
                  }}
                  onClose={() => setHistoryOpen(false)}
                />
              )}
            </div>

            {/* New session button */}
            <button
              onClick={handleNewSession}
              className="flex h-9 w-9 items-center justify-center rounded-md bg-white transition-colors hover:bg-zinc-50"
              style={{ border: "1px solid var(--color-border-soft)", color: "var(--color-ink-muted)" }}
              title="新对话"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>

            {/* Close button */}
            <button
              onClick={closeDrawer}
              className="flex h-9 w-9 items-center justify-center rounded-md transition-colors hover:bg-zinc-100"
              style={{ color: "var(--color-ink-muted)" }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Body: chat (left) + blueprint preview (right) */}
        <div className="flex min-h-0 flex-1">
          {/* Chat panel */}
          <div
            className="flex flex-1 flex-col"
            style={{ borderRight: draftBlueprint ? "1px solid var(--color-border-soft)" : "none" }}
          >
            <div className="flex-1 overflow-auto p-6">
              {messages.length === 0 ? (
                <div
                  className="flex h-full items-center justify-center text-sm"
                  style={{ color: "var(--color-ink-ghost)" }}
                >
                  {selectedLlm ? "描述你的项目想法，AI 会帮你拆解任务..." : "请先在上方选择 LLM"}
                </div>
              ) : (
                <>
                  {messages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`mb-4 max-w-[70%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                        msg.role === "user" ? "ml-auto" : "mr-auto"
                      }`}
                      style={{
                        backgroundColor: msg.role === "user" ? "white" : "var(--color-surface-alt)",
                        color: "var(--color-ink-soft)",
                      }}
                    >
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    </div>
                  ))}
                  {streamingText && (
                    <div
                      className="mb-4 mr-auto max-w-[70%] rounded-xl px-4 py-2.5 text-sm leading-relaxed"
                      style={{
                        backgroundColor: "var(--color-surface-alt)",
                        color: "var(--color-ink-soft)",
                      }}
                    >
                      <div className="whitespace-pre-wrap">
                        {streamingText}
                        <span className="ml-0.5 inline-block h-3 w-1 animate-pulse"
                              style={{ backgroundColor: "var(--color-ink-muted)" }} />
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            {/* Input area */}
            <div className="p-4">
              <div
                className="flex items-end gap-2 rounded-2xl bg-white p-2"
                style={{ border: "1px solid var(--color-border-soft)" }}
              >
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={activeSessionId ? "继续对话..." : "你好，请告诉我你当前有什么新的项目想法..."}
                  rows={2}
                  className="flex-1 resize-none rounded-md bg-transparent px-2 py-1 text-sm outline-none"
                />
                <button
                  className="flex h-9 w-9 items-center justify-center rounded-lg transition-colors hover:bg-zinc-100"
                  style={{ color: "var(--color-ink-muted)" }}
                  title="附件"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                  </svg>
                </button>
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || sendMessage.isPending || (!selectedLlm && !activeSessionId)}
                  className="flex h-9 items-center gap-1 rounded-lg px-3 text-sm text-white transition-opacity disabled:opacity-40"
                  style={{ backgroundColor: "var(--color-brand-500)" }}
                >
                  Send
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="12" y1="19" x2="12" y2="5" />
                    <polyline points="5 12 12 5 19 12" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          {/* Blueprint panel (only shown when blueprint exists) */}
          {draftBlueprint && (
            <div
              className="flex w-[45%] flex-col p-4"
              style={{ backgroundColor: "var(--color-surface)" }}
            >
              <TaskBlueprintEditor
                blueprint={draftBlueprint}
                onChange={setDraftBlueprint}
                onReEvaluate={handleReEvaluate}
                reEvaluating={reEvaluating}
              />
            </div>
          )}
        </div>

        {/* Bottom confirm bar */}
        {draftBlueprint && (
          <div
            className="px-6 py-4"
            style={{
              backgroundColor: "var(--color-card)",
              borderTop: "1px solid var(--color-border-soft)",
            }}
          >
            <button
              onClick={handleFinalize}
              disabled={finalize.isPending || draftBlueprint.tasks.length === 0}
              className="w-full rounded-lg py-3 text-base font-medium text-white transition-opacity disabled:opacity-50"
              style={{ backgroundColor: "var(--color-brand-500)" }}
            >
              {finalize.isPending ? "生成中..." : "确认"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function HistoryDropdown({
  activeId,
  onSelect,
  onClose,
}: {
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const { data: sessions } = useInceptionSessions();
  const items = (sessions ?? []) as InceptionSession[];

  // Close on outside click via simple click-away (parent handles it through state)
  void onClose;

  return (
    <div
      className="absolute right-0 top-11 z-40 max-h-80 w-72 overflow-auto rounded-lg bg-white shadow-xl"
      style={{ border: "1px solid var(--color-border-soft)" }}
    >
      <div
        className="px-3 py-2 text-xs font-medium"
        style={{
          color: "var(--color-ink-faint)",
          borderBottom: "1px solid var(--color-border-soft)",
        }}
      >
        历史会话
      </div>
      {items.length === 0 ? (
        <div className="p-4 text-center text-xs" style={{ color: "var(--color-ink-ghost)" }}>暂无</div>
      ) : (
        items.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left transition-colors hover:bg-zinc-50"
            style={{
              backgroundColor: activeId === s.id ? "var(--color-surface-alt)" : "transparent",
              borderBottom: "1px solid var(--color-border-soft)",
            }}
          >
            <div className="flex w-full items-center justify-between">
              <span className="truncate text-xs font-medium" style={{ color: "var(--color-ink-soft)" }}>
                {s.project_name ?? `会话 ${s.id.slice(-6)}`}
              </span>
              {s.is_draft && (
                <span
                  className="shrink-0 rounded px-1 text-[9px]"
                  style={{ backgroundColor: "rgba(245, 158, 11, 0.18)", color: "#92400e" }}
                >
                  草稿
                </span>
              )}
            </div>
            <span className="text-[10px]" style={{ color: "var(--color-ink-ghost)" }}>
              {s.created_at?.substring(0, 16)}
            </span>
          </button>
        ))
      )}
    </div>
  );
}

export default InceptionDrawer;
