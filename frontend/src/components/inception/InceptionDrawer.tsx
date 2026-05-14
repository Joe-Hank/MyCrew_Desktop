import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useInceptionStore } from "../../stores/useInceptionStore";
import { usePrefsStore } from "../../stores/usePrefsStore";
import {
  useInceptionSession,
  useCreateInceptionSession,
  useStreamInceptionMessage,
  useSendInceptionMessage,
  type Blueprint,
  type InceptionMessage,
} from "../../queries/useInceptionQuery";
import { useLlmProviders } from "../../queries/useLlmQuery";
import { useChatQueue } from "../../hooks/useChatQueue";
import { useEvent } from "../../hooks/useEvent";
import { apiFetch } from "../../net/api";
import { useQueryClient } from "@tanstack/react-query";
import TaskBlueprintEditor from "./TaskBlueprintEditor";
import ChoicePanel, { type ChoiceOption } from "./ChoicePanel";
import PathInputPanel from "./PathInputPanel";
import HistoryDropdown from "./HistoryDropdown";
import { useTemplates } from "../../queries/useTemplatesQuery";

function InceptionDrawer() {
  const navigate = useNavigate();
  const logExpanded = usePrefsStore((s) => s.logDrawerExpanded);
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
  const sendMessage = useSendInceptionMessage();
  const qc = useQueryClient();

  const selectedLlm = usePrefsStore((s) => s.inceptionLlm) ?? "";
  const selectedModel = usePrefsStore((s) => s.inceptionModel) ?? "";
  const thinking = usePrefsStore((s) => s.inceptionThinking);
  const setSelectedLlm = usePrefsStore((s) => s.setInceptionLlm);
  const setSelectedModel = usePrefsStore((s) => s.setInceptionModel);
  const setThinking = usePrefsStore((s) => s.setInceptionThinking);

  const [input, setInput] = useState("");
  const [reEvaluating, setReEvaluating] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null);
  const [lastPrompt, setLastPrompt] = useState<string>("");

  // Active-round streaming state — accumulates `inception.delta` deltas.
  const [streamingText, setStreamingText] = useState("");
  const [roundStartTs, setRoundStartTs] = useState<number | null>(null);

  // Pending structured-choice / path-input prompt from Plan Maker (e.g.
  // "pick a Unity template" or "supply iteration root path"). Cleared once
  // the user confirms; the confirmation goes through POST /choices.
  const [pendingChoice, setPendingChoice] = useState<{
    prompt: string;
    options: ChoiceOption[];
    context: string;
  } | null>(null);
  const [pendingPath, setPendingPath] = useState<{
    prompt: string;
    context: string;
  } | null>(null);
  // Confirmed picks for read-only history bubbles — once user confirms,
  // the live panel disappears and a compact summary stays visible above
  // the chat so they can see what they chose without scrolling.
  const [confirmedHistory, setConfirmedHistory] = useState<
    Array<
      | { kind: "template"; prompt: string; value: string; label: string }
      | { kind: "mode"; prompt: string; value: string; label: string }
      | { kind: "path"; prompt: string; value: string }
    >
  >([]);
  // When a round finishes we snapshot it so the chat can render a collapsed
  // "已思考 Ns" badge + a short summary bubble in place of the verbose
  // assistant message that's about to land via session refetch.
  const [completedRound, setCompletedRound] = useState<{
    durationS: number;
    thought: string;
    blueprint: Blueprint | null;
    assistantContent: string;
  } | null>(null);
  const [thoughtExpanded, setThoughtExpanded] = useState(false);
  // Blueprint captured during the in-flight round, before the assistant
  // message lands. Read by the completedRound snapshot.
  const inFlightBlueprintRef = useRef<Blueprint | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamBoxRef = useRef<HTMLDivElement>(null);

  // Stash latest values in refs so the chat-queue callback (created once)
  // can always see the current session / pref selection without re-binding.
  const sessionIdRef = useRef<string | null>(activeSessionId);
  sessionIdRef.current = activeSessionId;
  const ensureSessionRef = useRef<() => Promise<string | null>>(async () => null);

  ensureSessionRef.current = async (): Promise<string | null> => {
    if (sessionIdRef.current) return sessionIdRef.current;
    if (!selectedLlm) return null;
    const fullLlmId = selectedModel ? `${selectedLlm}:${selectedModel}` : selectedLlm;
    const res = await createSession.mutateAsync({
      llm_id: fullLlmId,
      thinking_mode: thinking,
    });
    if (res.ok && res.data) {
      const id = (res.data as { id: string }).id;
      setActiveSession(id);
      sessionIdRef.current = id;
      return id;
    }
    return null;
  };

  const sendLlmRound = useCallback(
    async (content: string, signal: AbortSignal) => {
      setLastPrompt(content);
      const sid = await ensureSessionRef.current();
      if (!sid) throw new Error("无法创建会话：请先在工具栏选择 LLM");
      await streamMessage.mutateAsync({ sessionId: sid, content, signal });
    },
    [streamMessage],
  );
  const chat = useChatQueue({ send: sendLlmRound });

  // Workflow created — Plan Maker called the create_workflow tool. Stash the
  // blueprint for both the right panel and the completed-round snapshot.
  const handleWorkflowCreated = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      const bp = msg.payload.blueprint as Blueprint | undefined;
      const pid = msg.payload.project_id as string | undefined;
      if (bp) {
        setDraftBlueprint(bp);
        inFlightBlueprintRef.current = bp;
      }
      if (pid) setCreatedProjectId(pid);
    },
    [activeSessionId, setDraftBlueprint],
  );
  useEvent("inception.workflow_created", handleWorkflowCreated);

  // Legacy salvage path — raw JSON blueprint detected in assistant text.
  const handleBlueprintEvent = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      const bp = msg.payload.blueprint as Blueprint | undefined;
      if (bp && msg.payload.session_id === activeSessionId) {
        setDraftBlueprint(bp);
        inFlightBlueprintRef.current = bp;
      }
    },
    [activeSessionId, setDraftBlueprint],
  );
  useEvent("inception.tasks_drafted", handleBlueprintEvent);

  // Streaming tokens — append to the in-flight buffer.
  const handleDelta = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      const text = (msg.payload.text as string) ?? "";
      if (text) setStreamingText((prev) => prev + text);
    },
    [activeSessionId],
  );
  useEvent("inception.delta", handleDelta);

  // Plan Maker lifecycle probes — feed the streaming subwindow with human-
  // readable progress lines so the user has continuous visual feedback even
  // when no LLM tokens are flowing (CrewAI's step_callback fires per *step*
  // completion, which leaves long silent gaps inside each LLM call).
  const handleProbe = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      const line = probeToLine(msg.payload);
      if (line) setStreamingText((prev) => prev + line + "\n");
    },
    [activeSessionId],
  );
  useEvent("inception.probe", handleProbe);

  // Plan Maker can't continue until the user provides a structured pick
  // (Unity template) or supplies the iteration root path. Backend emits
  // these events instead of running the LLM when the inception session
  // is missing the data.
  const handleChoices = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      setPendingChoice({
        prompt: (msg.payload.prompt as string) ?? "",
        options: ((msg.payload.options as unknown[]) ?? []) as ChoiceOption[],
        context: (msg.payload.context as string) ?? "",
      });
    },
    [activeSessionId],
  );
  useEvent("inception.choices", handleChoices);

  const handleInputPath = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      setPendingPath({
        prompt: (msg.payload.prompt as string) ?? "",
        context: (msg.payload.context as string) ?? "",
      });
    },
    [activeSessionId],
  );
  useEvent("inception.input_path", handleInputPath);

  // Confirm choice → POST /sessions/{id}/choices → clear pending panel
  // and snapshot the pick into confirmedHistory so a compact summary
  // bubble stays visible above the chat (the user shouldn't have to
  // scroll back to remember which template they picked).
  async function submitChoice(payload: {
    template_id?: string; root_path?: string; mode?: string;
  }) {
    const sid = sessionIdRef.current;
    if (!sid) return;
    try {
      await apiFetch(`/inceptions/sessions/${sid}/choices`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    } finally {
      if (payload.template_id && pendingChoice) {
        const opt = pendingChoice.options.find((o) => o.value === payload.template_id);
        setConfirmedHistory((h) => [...h, {
          kind: "template",
          prompt: pendingChoice.prompt,
          value: payload.template_id!,
          label: opt?.label ?? payload.template_id!,
        }]);
        setPendingChoice(null);
      } else if (payload.mode && pendingChoice) {
        const opt = pendingChoice.options.find((o) => o.value === payload.mode);
        setConfirmedHistory((h) => [...h, {
          kind: "mode",
          prompt: pendingChoice.prompt,
          value: payload.mode!,
          label: opt?.label ?? payload.mode!,
        }]);
        setPendingChoice(null);
      }
      if (payload.root_path && pendingPath) {
        setConfirmedHistory((h) => [...h, {
          kind: "path",
          prompt: pendingPath.prompt,
          value: payload.root_path!,
        }]);
        setPendingPath(null);
      }
    }
  }

  // Round finished — snapshot streamed text + blueprint into completedRound.
  // The persisted assistant message lands via session refetch shortly after;
  // we render the snapshot instead of the verbose message body.
  const handleFullMessage = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      if (msg.payload.role !== "assistant") return;
      const fullContent = (msg.payload.content as string) ?? "";
      const dur = roundStartTs ? Math.round((Date.now() - roundStartTs) / 1000) : 0;
      const thought = streamingText.trim() || fullContent;
      setCompletedRound({
        durationS: dur,
        thought,
        blueprint: inFlightBlueprintRef.current,
        assistantContent: fullContent,
      });
      setStreamingText("");
      setRoundStartTs(null);
      setThoughtExpanded(false);
    },
    [activeSessionId, roundStartTs, streamingText],
  );
  useEvent("inception.message", handleFullMessage);

  // Auto-scroll the streaming subwindow to the latest token.
  useEffect(() => {
    streamBoxRef.current?.scrollTo({
      top: streamBoxRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [streamingText]);

  // Reset round state when switching sessions.
  useEffect(() => {
    setCreatedProjectId(null);
    setLastPrompt("");
    setStreamingText("");
    setRoundStartTs(null);
    setCompletedRound(null);
    inFlightBlueprintRef.current = null;
  }, [activeSessionId]);

  // First-launch fallback: pick the first available provider/model.
  useEffect(() => {
    if (selectedLlm || !providers) return;
    const list = (providers as unknown as Array<{
      id: string;
      name: string;
      models?: Array<{ model_name: string }>;
    }>) ?? [];
    if (list.length === 0) return;
    const first = list[0];
    if (!first) return;
    setSelectedLlm(first.id);
    const firstModel = first.models?.[0]?.model_name;
    if (firstModel) setSelectedModel(firstModel);
  }, [providers, selectedLlm, setSelectedLlm, setSelectedModel]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages, chat.pending, chat.thinking, streamingText, completedRound]);

  if (!drawerOpen) return null;

  const providerList = (providers as unknown as Array<{ id: string; name: string; models?: Array<{ model_name: string }> }>) ?? [];
  const currentProvider = providerList.find((p) => p.id === selectedLlm);
  const modelOptions = currentProvider?.models ?? [];

  function handleSend() {
    const content = input.trim();
    if (!content) return;
    setInput("");
    // Starting a new round — reset all round-scoped UI state. The previous
    // completedRound snapshot (if any) falls back to the verbose persisted
    // assistant message in session.messages, which is the canonical history.
    setCompletedRound(null);
    setStreamingText("");
    setRoundStartTs(Date.now());
    inFlightBlueprintRef.current = null;
    chat.enqueue(content);
  }

  function handleStop() {
    chat.stop();
    setStreamingText("");
    setRoundStartTs(null);
  }

  /** 保存项目：项目已经在 DB 里了 (Plan Maker 已经调过 create_workflow)。
   *  这里把蓝图里用户选过的 agent_id 同步到 DB 中对应的 task，invalidate
   *  React Query 的项目列表（否则首页看不到新项目），然后关 drawer。 */
  async function handleSave() {
    if (!createdProjectId) {
      closeDrawer();
      navigate("/");
      return;
    }
    try {
      const detail = await apiFetch<{ tasks: Array<{ id: string; title: string }> }>(
        `/projects/${createdProjectId}`,
      );
      const dbTasks = detail.data?.tasks ?? [];
      const bp = draftBlueprint;
      if (bp && dbTasks.length > 0) {
        await Promise.all(
          bp.tasks.map(async (t, i) => {
            const dbTask = dbTasks[i];
            if (!dbTask || !t.agent_id) return;
            try {
              await apiFetch(`/workflow/tasks/${dbTask.id}`, {
                method: "PUT",
                body: JSON.stringify({ agent_id: t.agent_id }),
              });
            } catch (exc) {
              // eslint-disable-next-line no-console
              console.warn("inception.save_task_agent_failed", dbTask.id, exc);
            }
          }),
        );
      }
    } catch (exc) {
      // eslint-disable-next-line no-console
      console.warn("inception.save_lookup_failed", exc);
    }
    // Refresh the home grid (and the per-project detail cache) so the new
    // project card appears immediately after the drawer closes.
    await qc.invalidateQueries({ queryKey: ["projects"] });
    closeDrawer();
    navigate("/");
  }

  async function handleRegenerate() {
    if (!createdProjectId || !activeSessionId) return;
    try {
      const detail = await apiFetch<{ name: string }>(`/projects/${createdProjectId}`);
      const name = detail.data?.name ?? "";
      if (name) {
        await apiFetch(`/projects/${createdProjectId}`, {
          method: "DELETE",
          body: JSON.stringify({ name }),
        });
      }
    } catch (exc) {
      // eslint-disable-next-line no-console
      console.warn("inception.regenerate_delete_failed", exc);
    }
    setDraftBlueprint(null);
    setCreatedProjectId(null);
    setCompletedRound(null);
    if (lastPrompt) chat.enqueue(lastPrompt);
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
    setCompletedRound(null);
  }

  const rawMessages: InceptionMessage[] = session?.messages ?? [];
  // When we have a completedRound snapshot, hide the very last assistant
  // message in history (it's the verbose body of the round we just streamed,
  // rendered specially as a collapsible thought + summary bubble below).
  const visibleMessages = (() => {
    if (!completedRound) return rawMessages;
    let lastAssistantIdx = -1;
    for (let i = rawMessages.length - 1; i >= 0; i--) {
      const m = rawMessages[i];
      if (m && m.role === "assistant") {
        lastAssistantIdx = i;
        break;
      }
    }
    if (lastAssistantIdx === -1) return rawMessages;
    const lastAssistant = rawMessages[lastAssistantIdx];
    if (lastAssistant && lastAssistant.content === completedRound.assistantContent) {
      return rawMessages.filter((_, i) => i !== lastAssistantIdx);
    }
    return rawMessages;
  })();

  const drawerWidth = createdProjectId && draftBlueprint
    ? "min(64vw, 1100px)"
    : "min(38vw, 560px)";

  return (
    <>
      {/* Semi-transparent backdrop covering the home content (but not the
          left sidebar at x<110 — so 主导航 stays clickable). Sits below the
          drawer (z-30) so the chat + blueprint columns remain on top. The
          bottom edge matches the drawer's so the LogDrawer underneath is
          still reachable. Pointer events on the backdrop are absorbed by
          the div itself, blocking clicks from reaching the home grid. */}
      <div
        className="fixed z-20"
        style={{
          left: 110,
          right: 0,
          top: 0,
          bottom: logExpanded ? 224 : 28,
          backgroundColor: "rgba(0, 0, 0, 0.35)",
        }}
      />
      <div
        className="fixed z-30 flex flex-col shadow-2xl"
        style={{
          left: 110,
          top: 0,
          bottom: logExpanded ? 224 : 28,
          width: drawerWidth,
          backgroundColor: "var(--color-surface)",
          borderRight: "1px solid var(--color-border-soft)",
        }}
      >
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top toolbar */}
        <div
          className="flex items-center gap-1.5 px-3 py-2"
          style={{ borderBottom: "1px solid var(--color-border-soft)", backgroundColor: "var(--color-card)" }}
        >
          <select
            value={selectedLlm}
            onChange={(e) => {
              setSelectedLlm(e.target.value);
              setSelectedModel("");
            }}
            disabled={!!activeSessionId}
            className="min-w-0 max-w-[110px] rounded bg-white px-1.5 py-1 text-xs outline-none disabled:opacity-60"
            style={{ border: "1px solid var(--color-border-soft)" }}
            title="LLM"
          >
            <option value="">— LLM —</option>
            {providerList.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>

          <select
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={!selectedLlm || !!activeSessionId}
            className="min-w-0 max-w-[120px] rounded bg-white px-1.5 py-1 text-xs outline-none disabled:opacity-60"
            style={{ border: "1px solid var(--color-border-soft)" }}
            title="模型"
          >
            <option value="">— 模型 —</option>
            {modelOptions.map((m) => (
              <option key={m.model_name} value={m.model_name}>{m.model_name}</option>
            ))}
          </select>

          <div className="flex items-center gap-1 text-xs" style={{ color: "var(--color-ink-label)" }}>
            <span>思考</span>
            <button
              onClick={() => !activeSessionId && setThinking(!thinking)}
              disabled={!!activeSessionId}
              className="relative inline-flex h-4 w-7 items-center rounded-full transition-colors disabled:opacity-60"
              style={{ backgroundColor: thinking ? "#10b981" : "var(--color-surface-alt)" }}
            >
              <span
                className="absolute h-3 w-3 rounded-full bg-white shadow-sm transition-transform"
                style={{ transform: thinking ? "translateX(14px)" : "translateX(2px)" }}
              />
            </button>
          </div>

          <div className="ml-auto flex items-center gap-1">
            <div className="relative">
              <button
                onClick={() => setHistoryOpen((v) => !v)}
                className="flex h-7 w-7 items-center justify-center rounded bg-white transition-colors hover:bg-zinc-50"
                style={{ border: "1px solid var(--color-border-soft)", color: "var(--color-ink-muted)" }}
                title="历史会话"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
                  onActiveDeleted={() => {
                    setActiveSession(null);
                    setDraftBlueprint(null);
                  }}
                />
              )}
            </div>

            <button
              onClick={handleNewSession}
              className="flex h-7 w-7 items-center justify-center rounded bg-white transition-colors hover:bg-zinc-50"
              style={{ border: "1px solid var(--color-border-soft)", color: "var(--color-ink-muted)" }}
              title="新对话"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>

            <button
              onClick={closeDrawer}
              className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:bg-zinc-100"
              style={{ color: "var(--color-ink-muted)" }}
              title="关闭"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Body: chat (left) + blueprint preview (right) */}
        <div className="flex min-h-0 flex-1">
          <div
            className="flex flex-1 flex-col"
            style={{ borderRight: draftBlueprint ? "1px solid var(--color-border-soft)" : "none" }}
          >
            <div className="flex-1 overflow-auto p-6">
              {visibleMessages.length === 0
                && chat.pending.length === 0
                && !chat.thinking
                && !completedRound ? (
                !selectedLlm ? (
                  <div
                    className="flex h-full items-center justify-center text-sm"
                    style={{ color: "var(--color-ink-ghost)" }}
                  >
                    请先在上方选择 LLM
                  </div>
                ) : !activeSessionId ? (
                  // Pre-session template picker — user hasn't even created
                  // an inception session yet. Show template cards directly
                  // so the user doesn't have to type a dummy message just
                  // to trigger the choice flow. On confirm we create the
                  // session with template_id pre-baked.
                  <InitialTemplateChoice
                    onConfirm={async (templateId) => {
                      if (!selectedLlm) return;
                      const fullLlmId = selectedModel
                        ? `${selectedLlm}:${selectedModel}`
                        : selectedLlm;
                      const res = await createSession.mutateAsync({
                        llm_id: fullLlmId,
                        thinking_mode: thinking,
                        mode: "create",
                        template_id: templateId,
                      });
                      if (res.ok && res.data) {
                        const id = (res.data as { id: string }).id;
                        setActiveSession(id);
                      }
                    }}
                  />
                ) : (
                  <div
                    className="flex h-full items-center justify-center text-sm"
                    style={{ color: "var(--color-ink-ghost)" }}
                  >
                    描述你的项目想法，AI 会帮你拆解任务...
                  </div>
                )
              ) : (
                <>
                  {visibleMessages.map((msg) => (
                    <div
                      key={msg.id}
                      className={`mb-4 max-w-[70%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                        msg.role === "user" ? "ml-auto" : "mr-auto"
                      }`}
                      style={{
                        backgroundColor: msg.role === "user" ? "#95EC69" : "#FFFFFF",
                        color: "#1F1F1F",
                      }}
                    >
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    </div>
                  ))}

                  {/* Local user bubbles for messages still in the queue or
                      mid-flight. Cleared after the round's server invalidate
                      lands in the cache. */}
                  {chat.pending.map((p) => (
                    <div
                      key={p.id}
                      className="mb-4 ml-auto max-w-[70%] rounded-xl px-4 py-2.5 text-sm leading-relaxed"
                      style={{ backgroundColor: "#95EC69", color: "#1F1F1F" }}
                    >
                      <div className="whitespace-pre-wrap">{p.content}</div>
                    </div>
                  ))}

                  {/* "正在思考中" — Plan Maker is between steps and no delta
                      has arrived yet. Persists until the first token of the
                      streaming subwindow lands. */}
                  {chat.thinking && !streamingText && (
                    <div
                      className="mb-4 mr-auto flex max-w-[70%] items-center gap-2 rounded-xl px-4 py-2.5 text-sm"
                      style={{ backgroundColor: "#FFFFFF", color: "#7A7A7A" }}
                    >
                      <span className="flex gap-1">
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current"
                              style={{ animationDelay: "0ms" }} />
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current"
                              style={{ animationDelay: "150ms" }} />
                        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current"
                              style={{ animationDelay: "300ms" }} />
                      </span>
                      <span>Plan Maker 正在思考中...</span>
                    </div>
                  )}

                  {/* Streaming subwindow — max 5 visible lines, internal
                      scroll, auto-stick to bottom. Frontier-chat "thinking
                      content" UX: shows the LLM's reasoning as it streams. */}
                  {streamingText && (
                    <div
                      className="mb-4 mr-auto max-w-[85%] rounded-xl border bg-zinc-50 p-3"
                      style={{ borderColor: "var(--color-border-soft)" }}
                    >
                      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide"
                           style={{ color: "var(--color-ink-ghost)" }}>
                        <span className="flex gap-0.5">
                          <span className="h-1 w-1 animate-bounce rounded-full"
                                style={{ backgroundColor: "var(--color-ink-ghost)", animationDelay: "0ms" }} />
                          <span className="h-1 w-1 animate-bounce rounded-full"
                                style={{ backgroundColor: "var(--color-ink-ghost)", animationDelay: "150ms" }} />
                          <span className="h-1 w-1 animate-bounce rounded-full"
                                style={{ backgroundColor: "var(--color-ink-ghost)", animationDelay: "300ms" }} />
                        </span>
                        <span>思考中</span>
                      </div>
                      <div
                        ref={streamBoxRef}
                        className="max-h-[7.5rem] overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed"
                        style={{ color: "var(--color-ink-muted)" }}
                      >
                        {streamingText}
                      </div>
                    </div>
                  )}

                  {/* Completed-round snapshot: collapsed thought + summary. */}
                  {completedRound && !chat.thinking && (
                    <>
                      <button
                        onClick={() => setThoughtExpanded((v) => !v)}
                        className="mb-2 mr-auto flex items-center gap-1.5 rounded-lg border bg-white px-2.5 py-1 text-[11px] transition-colors hover:bg-zinc-50"
                        style={{
                          borderColor: "var(--color-border-soft)",
                          color: "var(--color-ink-muted)",
                        }}
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
                             stroke="currentColor" strokeWidth="2"
                             style={{
                               transform: thoughtExpanded ? "rotate(90deg)" : "rotate(0)",
                               transition: "transform 150ms",
                             }}>
                          <polyline points="9 18 15 12 9 6" />
                        </svg>
                        <span>已思考 {completedRound.durationS}s · 点击{thoughtExpanded ? "收起" : "展开"}</span>
                      </button>
                      {thoughtExpanded && (
                        <div
                          className="mb-4 mr-auto max-w-[85%] rounded-xl border bg-zinc-50 p-3"
                          style={{ borderColor: "var(--color-border-soft)" }}
                        >
                          <div className="max-h-[12rem] overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed"
                               style={{ color: "var(--color-ink-muted)" }}>
                            {completedRound.thought}
                          </div>
                        </div>
                      )}
                      <div
                        className="mb-4 mr-auto max-w-[70%] rounded-xl px-4 py-2.5 text-sm leading-relaxed"
                        style={{ backgroundColor: "#FFFFFF", color: "#1F1F1F" }}
                      >
                        <div className="whitespace-pre-wrap">
                          {summariseRound(completedRound.blueprint, completedRound.assistantContent)}
                        </div>
                      </div>
                    </>
                  )}

                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            {/* Read-only history of confirmed picks — one compact bubble
                per template / mode / path choice. Stays visible above the
                textarea so the user never has to scroll back to see what
                they picked. */}
            {confirmedHistory.length > 0 && (
              <div className="space-y-1 px-4 pt-2">
                {confirmedHistory.map((h, i) => (
                  h.kind === "path" ? (
                    <PathInputPanel
                      key={i}
                      prompt={h.prompt}
                      onConfirm={() => undefined}
                      readOnly
                      confirmedPath={h.value}
                    />
                  ) : (
                    <ChoicePanel
                      key={i}
                      prompt={h.prompt}
                      options={[{ value: h.value, label: h.label }]}
                      onConfirm={() => undefined}
                      readOnly
                      confirmedValue={h.value}
                    />
                  )
                ))}
              </div>
            )}

            {/* Pending structured pick (template) or path-input prompt.
                Renders above the textarea; user confirms to unlock chat. */}
            {pendingChoice && (
              <div className="px-4 pt-2">
                <ChoicePanel
                  prompt={pendingChoice.prompt}
                  options={pendingChoice.options}
                  onConfirm={(value) => {
                    if (pendingChoice.context === "template_selection") {
                      submitChoice({ template_id: value });
                    } else {
                      submitChoice({ mode: value });
                    }
                  }}
                />
              </div>
            )}
            {pendingPath && (
              <div className="px-4 pt-2">
                <PathInputPanel
                  prompt={pendingPath.prompt}
                  onConfirm={(p) => submitChoice({ root_path: p })}
                />
              </div>
            )}

            {/* Input area — textarea stays unlocked while thinking; new input
                joins the queue. Send flips to Stop only while a round is
                mid-flight. */}
            <div className="p-4">
              <div
                className="flex items-end gap-2 rounded-2xl bg-white p-2"
                style={{ border: "1px solid var(--color-border-soft)" }}
              >
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={
                    chat.thinking
                      ? "Plan Maker 正在思考…你可以继续输入，将在本轮结束后一并发送"
                      : activeSessionId
                        ? "继续对话..."
                        : "你好，请告诉我你当前有什么新的项目想法..."
                  }
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
                {chat.thinking ? (
                  <button
                    onClick={handleStop}
                    className="flex h-9 items-center gap-1 rounded-lg px-3 text-sm text-white transition-opacity hover:opacity-90"
                    style={{ backgroundColor: "#737373" }}
                    title="终止 AI 响应"
                  >
                    Stop
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                      <rect x="6" y="6" width="12" height="12" rx="1" />
                    </svg>
                  </button>
                ) : (
                  <button
                    onClick={handleSend}
                    disabled={!input.trim() || (!selectedLlm && !activeSessionId)}
                    className="flex h-9 items-center gap-1 rounded-lg px-3 text-sm text-white transition-opacity disabled:opacity-40"
                    style={{ backgroundColor: "var(--color-brand-500)" }}
                  >
                    Send
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <line x1="12" y1="19" x2="12" y2="5" />
                      <polyline points="5 12 12 5 19 12" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Blueprint panel — shown only after Plan Maker's create_workflow
              tool has persisted the project. Bottom action bar lives inside
              this column now (per spec: 重新生成 / 保存项目 belong with the
              blueprint, not the chat). */}
          {createdProjectId && draftBlueprint && (
            <div
              className="flex w-[45%] min-w-[360px] flex-col transition-all duration-200"
              style={{ backgroundColor: "var(--color-surface)" }}
            >
              <div className="min-h-0 flex-1 p-4">
                <TaskBlueprintEditor
                  blueprint={draftBlueprint}
                  onChange={setDraftBlueprint}
                  onReEvaluate={handleReEvaluate}
                  reEvaluating={reEvaluating}
                />
              </div>
              <div
                className="px-4 py-3"
                style={{
                  backgroundColor: "var(--color-card)",
                  borderTop: "1px solid var(--color-border-soft)",
                }}
              >
                <div className="flex gap-2">
                  <button
                    onClick={handleRegenerate}
                    disabled={chat.thinking}
                    className="rounded-lg border bg-white px-3 py-2 text-xs font-medium transition-colors hover:bg-zinc-50 disabled:opacity-40"
                    style={{
                      borderColor: "var(--color-border-soft)",
                      color: "var(--color-ink-label)",
                    }}
                    title="删除当前方案并让 Plan Maker 重新生成"
                  >
                    {chat.thinking ? "生成中..." : "重新生成"}
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={chat.thinking}
                    className="flex-1 rounded-lg py-2 text-sm font-medium text-white transition-opacity disabled:opacity-40"
                    style={{ backgroundColor: "var(--color-brand-500)" }}
                  >
                    保存项目
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      </div>
    </>
  );
}

/** Map an inception.probe payload into a single readable Chinese line for the
 *  streaming subwindow. Returning null hides the probe (too low-level for the
 *  end user). Numeric / preview fields are surfaced inline so the line gives
 *  meaningful context, not just the raw label. */
function probeToLine(payload: Record<string, unknown>): string | null {
  const label = payload.label as string | undefined;
  if (!label) return null;
  const s = (k: string) => (payload[k] as string | undefined) ?? "";
  switch (label) {
    case "enter": return "→ Plan Maker 已启动";
    case "llm_resolved": return `→ 选定 LLM：${s("provider")} / ${s("model")}`;
    case "llm_built": return "→ LLM 实例就绪";
    case "backstory_rendered": return `→ Plan Maker 提示已渲染（${s("chars")} 字符）`;
    case "description_built": return "→ 任务上下文已构建";
    case "agent_and_task_built": return "→ Agent 与任务定义完成";
    case "crew_built": return `→ 启动 Crew 推理（${s("timeout_s")}s 超时上限）`;
    case "step": {
      const prev = s("preview").trim();
      return `▸ 步骤 ${s("n")}${prev ? `: ${prev}` : ""}`;
    }
    case "kickoff_returned": return `✓ 推理完成（共 ${s("steps")} 步）`;
    case "kickoff_timeout": return `⚠️ Plan Maker 超时（${s("timeout_s")}s）`;
    case "kickoff_failed": return `⚠️ Plan Maker 中断：${s("error")}`;
    case "result_unpacked": return `→ 结果解析（${s("text_chars")} 字符）`;
    case "salvage_persisted": return `✓ 任务方案已持久化（${s("tasks")} 个任务）`;
    case "early_exit_workflow_already_created": return `✓ 工作流已生成 (${s("reason")})`;
    // Suppress: lock_acquired, assistant_persisted, probe_broadcast_failed
    default: return null;
  }
}

/** Short user-facing summary shown in place of the verbose Plan Maker reply.
 *  Prefers a count-based summary when a blueprint is attached; otherwise
 *  falls back to the assistant's own text (e.g. for clarifying questions
 *  Plan Maker asks before producing a blueprint). */
function summariseRound(bp: Blueprint | null, fallback: string): string {
  if (bp && bp.tasks && bp.tasks.length > 0) {
    const name = bp.name ? `「${bp.name}」` : "";
    return `我已帮你设计完整任务路线${name}，包含 ${bp.tasks.length} 个任务（执行模式：${bp.execution_kind}）。你可以在右侧手动编辑，或把修改的需求继续告诉我。`;
  }
  return fallback || "（无回复）";
}


/** Pre-session template picker — shown when the drawer is open but no
 *  inception session exists yet (the "新建项目" flow's very first screen).
 *  Skips the "type a message → backend emits choices" round-trip so the
 *  user lands on something immediately. */
function InitialTemplateChoice({
  onConfirm,
}: {
  onConfirm: (templateId: string) => void;
}) {
  const { data: templates, isLoading } = useTemplates();
  if (isLoading || !templates) {
    return (
      <div
        className="flex h-full items-center justify-center text-sm"
        style={{ color: "var(--color-ink-ghost)" }}
      >
        加载模板中…
      </div>
    );
  }
  const options: ChoiceOption[] = templates.map((t) => ({
    value: t.id,
    label: t.label,
    description: t.description,
  }));
  return (
    <div className="flex h-full items-start justify-center p-2">
      <div className="w-full max-w-2xl">
        <ChoicePanel
          prompt="你想做什么类型的 Unity 游戏？选一个模板，我会基于它的目录结构来设计任务。"
          options={options}
          onConfirm={onConfirm}
        />
      </div>
    </div>
  );
}

export default InceptionDrawer;
