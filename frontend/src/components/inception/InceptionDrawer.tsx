import { useState, useRef, useEffect, useCallback } from "react";
import { useInceptionStore } from "../../stores/useInceptionStore";
import {
  useInceptionSession,
  useCreateInceptionSession,
  useSendInceptionMessage,
  useFinalizeInception,
  type Blueprint,
} from "../../queries/useInceptionQuery";
import { useLlmProviders } from "../../queries/useLlmQuery";
import { useEvent } from "../../hooks/useEvent";
import TaskBlueprintEditor from "./TaskBlueprintEditor";
import FileIndexer, { type IndexedPath } from "./FileIndexer";
import SessionList from "./SessionList";

function InceptionDrawer() {
  const {
    drawerOpen, closeDrawer, activeSessionId, setActiveSession,
    draftBlueprint, setDraftBlueprint,
  } = useInceptionStore();
  const { data: session } = useInceptionSession(activeSessionId);
  const { data: providers } = useLlmProviders();
  const createSession = useCreateInceptionSession();
  const sendMessage = useSendInceptionMessage();
  const finalize = useFinalizeInception();

  const [input, setInput] = useState("");
  const [selectedLlm, setSelectedLlm] = useState("");
  const [thinking, setThinking] = useState(false);
  const [reEvaluating, setReEvaluating] = useState(false);
  const [indexedPaths, setIndexedPaths] = useState<IndexedPath[]>([]);
  const [showNewSession, setShowNewSession] = useState(false);
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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages]);

  // Save unsent input to localStorage on close
  useEffect(() => {
    if (!drawerOpen && activeSessionId && input.trim()) {
      localStorage.setItem(`inception_draft_${activeSessionId}`, input);
    }
  }, [drawerOpen, activeSessionId, input]);

  // Restore draft input when session changes
  useEffect(() => {
    if (activeSessionId) {
      const saved = localStorage.getItem(`inception_draft_${activeSessionId}`);
      if (saved) {
        setInput(saved);
        localStorage.removeItem(`inception_draft_${activeSessionId}`);
      } else {
        setInput("");
      }
    }
  }, [activeSessionId]);

  if (!drawerOpen) return null;

  async function handleNewSession() {
    if (!selectedLlm) return;
    const res = await createSession.mutateAsync({
      llm_id: selectedLlm,
      thinking_mode: thinking,
    });
    if (res.ok && res.data) {
      setActiveSession((res.data as { id: string }).id);
      setShowNewSession(false);
    }
  }

  function handleSelectSession(id: string) {
    setActiveSession(id);
    setDraftBlueprint(null);
    setIndexedPaths([]);
    setShowNewSession(false);
  }

  async function handleSend() {
    if (!input.trim() || !activeSessionId) return;
    const content = input.trim();
    setInput("");
    localStorage.removeItem(`inception_draft_${activeSessionId}`);
    await sendMessage.mutateAsync({ sessionId: activeSessionId, content });
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

  const messages = session?.messages ?? [];
  const providerList = (providers as unknown as Array<Record<string, unknown>>) ?? [];
  const needsSetup = !activeSessionId || showNewSession;

  return (
    <div className="fixed inset-y-0 left-[200px] z-40 flex" style={{ width: "calc(100% - 200px)" }}>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20" onClick={closeDrawer} />

      {/* Session list sidebar */}
      <div className="relative z-10 h-full w-48 shrink-0 border-r border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
        <SessionList
          activeId={activeSessionId}
          onSelect={handleSelectSession}
          onNew={() => {
            setActiveSession(null);
            setShowNewSession(true);
            setDraftBlueprint(null);
          }}
        />
      </div>

      {/* Main drawer */}
      <div
        className="relative z-10 flex h-full flex-col border-r border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900"
        style={{ width: draftBlueprint ? "calc(100% - 48px - 280px)" : "calc(62% - 48px)" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
          <h2 className="text-sm font-semibold">
            {activeSessionId ? "项目对话" : "新建项目"}
          </h2>
          <button onClick={closeDrawer} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200">
            ✕
          </button>
        </div>

        {/* LLM Selection */}
        {needsSetup && (
          <div className="flex flex-1 flex-col items-center justify-center p-8">
            <div className="w-full max-w-sm space-y-4">
              <h3 className="text-center text-sm font-medium text-zinc-600 dark:text-zinc-300">
                选择 LLM 开始新对话
              </h3>
              <select
                value={selectedLlm}
                onChange={(e) => setSelectedLlm(e.target.value)}
                className="w-full rounded border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
              >
                <option value="">选择 LLM...</option>
                {providerList.map((p) => (
                  <option key={p.id as string} value={p.id as string}>
                    {p.name as string}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-2 text-xs text-zinc-500">
                <input
                  type="checkbox"
                  checked={thinking}
                  onChange={(e) => setThinking(e.target.checked)}
                  className="h-3 w-3"
                />
                思考模式
              </label>
              <button
                onClick={handleNewSession}
                disabled={!selectedLlm || createSession.isPending}
                className="w-full rounded bg-blue-500 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                开始对话
              </button>
            </div>
          </div>
        )}

        {/* Chat area */}
        {activeSessionId && !showNewSession && (
          <div className="flex flex-1 flex-col overflow-hidden">
            <div className="flex-1 overflow-auto p-4">
              {messages.length === 0 && (
                <div className="flex h-full items-center justify-center text-sm text-zinc-400">
                  描述你的项目想法...
                </div>
              )}
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`mb-3 rounded-lg px-3 py-2 text-sm ${
                    msg.role === "user"
                      ? "ml-8 bg-blue-50 dark:bg-blue-950"
                      : "mr-8 bg-zinc-100 dark:bg-zinc-800"
                  }`}
                >
                  <div className="mb-1 text-xs font-medium text-zinc-500">
                    {msg.role === "user" ? "你" : "AI"}
                  </div>
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* File indexer */}
            <div className="border-t border-zinc-200 px-3 py-2 dark:border-zinc-700">
              <FileIndexer
                sessionId={activeSessionId}
                indexed={indexedPaths}
                onAdd={(entry) => setIndexedPaths((prev) => [...prev, entry])}
                onRemove={(path) => setIndexedPaths((prev) => prev.filter((p) => p.path !== path))}
              />
            </div>

            {/* Input */}
            <div className="border-t border-zinc-200 p-3 dark:border-zinc-700">
              <div className="flex gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="描述你的项目想法..."
                  rows={2}
                  className="flex-1 resize-none rounded border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-800"
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || sendMessage.isPending}
                  className="shrink-0 rounded bg-blue-500 px-4 text-xs font-medium text-white disabled:opacity-50"
                >
                  {sendMessage.isPending ? "..." : "发送"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Blueprint panel */}
      {activeSessionId && !showNewSession && draftBlueprint && (
        <div className="relative z-10 h-full w-[280px] shrink-0 overflow-auto border-r border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-950">
          <TaskBlueprintEditor
            blueprint={draftBlueprint}
            onChange={setDraftBlueprint}
            onFinalize={handleFinalize}
            onReEvaluate={handleReEvaluate}
            finalizing={finalize.isPending}
            reEvaluating={reEvaluating}
          />
        </div>
      )}
    </div>
  );
}

export default InceptionDrawer;
