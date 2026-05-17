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
import PMDebugLog from "./PMDebugLog";
import { useTemplates } from "../../queries/useTemplatesQuery";
import { usePmState, type PMState } from "../../hooks/usePmState";

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
  // PM v3 — backend in-memory draft state. Drives the right-panel debug
  // log + the 保存/从断点重来/取消 buttons. status='idle' = no PM round
  // ever started on this session (or session changed); other statuses
  // mean the right panel should take over from the legacy iterate/
  // DraftingSkeleton path.
  const { state: pmState, refetch: refetchPmState } = usePmState(activeSessionId);
  const { data: providers } = useLlmProviders();
  const createSession = useCreateInceptionSession();
  const streamMessage = useStreamInceptionMessage();
  const sendMessage = useSendInceptionMessage();
  const qc = useQueryClient();

  const selectedLlm = usePrefsStore((s) => s.inceptionLlm) ?? "";
  const selectedModel = usePrefsStore((s) => s.inceptionModel) ?? "";
  const setSelectedLlm = usePrefsStore((s) => s.setInceptionLlm);
  const setSelectedModel = usePrefsStore((s) => s.setInceptionModel);

  const [input, setInput] = useState("");
  const [reEvaluating, setReEvaluating] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null);
  const [lastPrompt, setLastPrompt] = useState<string>("");
  // Surface backend / network failures from the pre-session template
  // picker — without this, mutateAsync errors silently and the confirm
  // button looks "unresponsive" (user report 2026-05-16).
  const [templateError, setTemplateError] = useState<string>("");

  // Active-round streaming state — accumulates `inception.delta` deltas.
  const [streamingText, setStreamingText] = useState("");
  const [roundStartTs, setRoundStartTs] = useState<number | null>(null);

  // "Drafting" = a create/iterate sub-agent has started its kickoff but
  // hasn't yet emitted inception.workflow_created. We open the right
  // panel with a skeleton in this window so the user has immediate
  // feedback instead of staring at a chat-only column for 10-30s.
  const [drafting, setDrafting] = useState<null | {
    intent: "create_new" | "iterate_existing";
    mode: "create" | "iterate";
  }>(null);

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

  // Drafting started — a create_new / iterate_existing sub-agent picked
  // up the round. Open the right panel skeleton immediately so the user
  // sees "生成中…" while waiting for create_workflow to land.
  const handleDraftingStarted = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      const intent = msg.payload.intent as "create_new" | "iterate_existing" | undefined;
      const mode = msg.payload.mode as "create" | "iterate" | undefined;
      if (!intent || !mode) return;
      setDrafting({ intent, mode });
    },
    [activeSessionId],
  );
  useEvent("inception.drafting_started", handleDraftingStarted);

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
      // Tasks have landed — drafting skeleton can transition to the real
      // blueprint editor, but keep `drafting` flag so any unassigned
      // task pills still show the "agent 待分配" shimmer until
      // inception.agents_assigned arrives.
    },
    [activeSessionId, setDraftBlueprint],
  );
  useEvent("inception.workflow_created", handleWorkflowCreated);

  // Agents assigned — merge the task→agent mapping into the in-flight
  // blueprint so the right panel pills flip "待分配" → real role label
  // without a server round-trip.
  const handleAgentsAssigned = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      const assignments = (msg.payload.assignments as Array<{
        task_id: string;
        task_index: number;
        agent_id: string;
        agent_role: string;
      }>) ?? [];
      if (assignments.length === 0) {
        setDrafting(null);
        return;
      }
      const prev = inFlightBlueprintRef.current;
      if (prev) {
        const byIndex = new Map(assignments.map((a) => [a.task_index, a]));
        const newTasks = prev.tasks.map((t, i) => {
          const a = byIndex.get(i);
          return a
            ? { ...t, agent_id: a.agent_id, agent_role: a.agent_role }
            : t;
        });
        const next: Blueprint = { ...prev, tasks: newTasks };
        inFlightBlueprintRef.current = next;
        setDraftBlueprint(next);
      }
      setDrafting(null);
    },
    [activeSessionId, setDraftBlueprint],
  );
  useEvent("inception.agents_assigned", handleAgentsAssigned);

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

  // Plan Maker per-stage IO trace — surface the friendly per-sub-agent
  // input/output in the live thinking subframe so the user always sees
  // SOMETHING meaningful, even when the LLM doesn't stream tokens.
  const handleSubAgentIo = useCallback(
    (msg: { payload: Record<string, unknown> }) => {
      if (msg.payload.session_id !== activeSessionId) return;
      const sub = (msg.payload.sub_agent as string) ?? "";
      const out = (msg.payload.output_preview as string) ?? "";
      const label = SUB_AGENT_LABELS[sub] ?? sub;
      const conf = msg.payload.confidence != null
        ? `（置信 ${msg.payload.confidence}）` : "";
      const line = `✦ ${label}${conf}：${out.slice(0, 120)}${out.length > 120 ? "…" : ""}`;
      setStreamingText((prev) => prev + line + "\n");
    },
    [activeSessionId],
  );
  useEvent("plan_maker.sub_agent_io", handleSubAgentIo);

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
    setDrafting(null);
    inFlightBlueprintRef.current = null;
  }, [activeSessionId]);

  // Safety: clear "drafting" skeleton once the round finishes, in case the
  // backend never emitted inception.agents_assigned (e.g. assign_agents
  // silently skipped — drafting must not stay stuck on forever).
  useEffect(() => {
    if (!chat.thinking && drafting) {
      const t = setTimeout(() => setDrafting(null), 1500);
      return () => clearTimeout(t);
    }
    return;
  }, [chat.thinking, drafting]);

  // PM v3 — when the crew finishes ('ready'), mirror its draft into the
  // inception store's draftBlueprint so the inline TaskBlueprintEditor
  // can edit it. Edits stay in Zustand; the 保存项目 button forwards
  // the latest draftBlueprint to /pm/save as override_blueprint so
  // user-side edits are honoured. Skip if user already started editing
  // a different blueprint (legacy iterate path).
  useEffect(() => {
    if (pmState.status === "ready" && pmState.draft_blueprint && !draftBlueprint) {
      setDraftBlueprint(pmState.draft_blueprint as unknown as Blueprint);
    }
    // Clear local mirror when the cache draft disappears (post-save /
    // 新建对话 / cancel) so the next round starts clean.
    if (pmState.status === "idle" && draftBlueprint && !createdProjectId) {
      setDraftBlueprint(null);
    }
  }, [
    pmState.status,
    pmState.draft_blueprint,
    draftBlueprint,
    createdProjectId,
    setDraftBlueprint,
  ]);

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

  // NOTE: Don't `return null` when closed — PM v3 keeps the drawer
  // mounted (with display:none) so that:
  //   1. Active fetches (the blocked POST /messages/stream) keep their
  //      reference to setState callbacks even if user navigates away
  //   2. WS event handlers (useEvent) stay subscribed so debug logs
  //      keep accumulating in the right hooks while the drawer is hidden
  //   3. Reopening the drawer instantly shows current state instead of
  //      re-fetching everything from scratch

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

  // De-dupe local pending bubbles against persisted user messages.
  // Once a user message has been persisted server-side and landed in
  // `rawMessages` (via React Query refetch or WS-driven invalidate),
  // the matching `chat.pending` entry would otherwise render *twice*
  // until `runLoop` clears it. Filter out any pending whose content
  // already appears as a recent user-role message.
  const recentUserContents = new Set(
    rawMessages.filter((m) => m.role === "user").slice(-8).map((m) => m.content),
  );
  const visiblePending = chat.pending.filter((p) => !recentUserContents.has(p.content));

  // Right panel auto-show: (a) we already have a blueprint, OR
  // (b) a create/iterate sub-agent is mid-draft, OR (c) the PM v3
  // cache has any state besides idle (running / ready / failed /
  // cancelled — all of which deserve the debug log panel).
  const pmActive = pmState.status !== "idle";
  const autoShowRightPanel =
    !!(createdProjectId && draftBlueprint) || !!drafting || pmActive;
  // Manual override (2026-05-17): top-header toggle button lets the
  // user force the right panel open even when there's no PM activity
  // (state 1 in the spec: 空栏 + 底部"左侧输入创作思路"提示) and
  // force it closed at any time. null = follow auto rule.
  const [manualRightPanelOpen, setManualRightPanelOpen] =
    useState<boolean | null>(null);
  const showRightPanel = manualRightPanelOpen ?? autoShowRightPanel;
  // 2026-05-17 UI lock: the chat column keeps a FIXED width regardless
  // of right-panel state. Opening / closing the panel only widens or
  // shrinks the drawer's right edge — the chat toolbar (model selector
  // through close button) stays anchored at the same x-coordinate so
  // the buttons stop "dancing".
  const CHAT_COL_WIDTH = "min(38vw, 560px)";
  const RIGHT_PANEL_WIDTH = "min(45vw, 540px)";
  const drawerWidth = showRightPanel
    ? `calc(${CHAT_COL_WIDTH} + ${RIGHT_PANEL_WIDTH})`
    : CHAT_COL_WIDTH;

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
          // PM v3 — hide via display:none instead of unmounting so all
          // hooks (useChatQueue / useEvent / usePmState) keep their
          // subscriptions alive across drawer open/close.
          display: drawerOpen ? undefined : "none",
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
          display: drawerOpen ? undefined : "none",
        }}
      >
      <div className="flex flex-1 overflow-hidden">
        {/* Chat column. Holds the toolbar + scrollback + input.
            Pinned to CHAT_COL_WIDTH so the toolbar above it never
            widens when the right panel opens — buttons stay anchored. */}
        <div
          className="flex flex-col"
          style={{
            width: CHAT_COL_WIDTH,
            flexShrink: 0,
            borderRight: showRightPanel
              ? "1px solid var(--color-border-soft)"
              : "none",
          }}
        >
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

          <div className="ml-auto flex items-center gap-1">
            <div className="relative">
              <button
                onClick={() => setHistoryOpen((v) => !v)}
                className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:opacity-80"
                style={{
                  backgroundColor: "var(--color-card)",
                  border: "1px solid var(--color-border-soft)",
                  color: "var(--color-ink-muted)",
                }}
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
              className="flex h-7 w-7 items-center justify-center rounded transition-colors hover:opacity-80"
              style={{
                backgroundColor: "var(--color-card)",
                border: "1px solid var(--color-border-soft)",
                color: "var(--color-ink-muted)",
              }}
              title="新对话"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>

            {/* 2026-05-17: manual right-panel toggle. Each click flips
                between forced-open and forced-closed; null state (auto)
                gets seeded by the user's first click based on current
                effective state. Theme-aware colors (var(--color-*))
                so dark mode renders correctly — was hardcoded "white"
                which stayed literal white in dark mode. Open state is
                a subtle gray fill (--color-surface-alt) rather than
                brand color, per user note "灰色即可". */}
            <button
              onClick={() =>
                setManualRightPanelOpen(showRightPanel ? false : true)
              }
              className="flex h-7 w-7 items-center justify-center rounded transition-colors"
              style={{
                backgroundColor: showRightPanel
                  ? "var(--color-surface-alt)"
                  : "var(--color-card)",
                border: "1px solid var(--color-border-soft)",
                color: showRightPanel
                  ? "var(--color-ink-soft)"
                  : "var(--color-ink-muted)",
              }}
              title={showRightPanel ? "关闭任务/LLM 日志栏" : "打开任务/LLM 日志栏"}
            >
              {/* Sidebar/panel-right icon */}
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" strokeWidth="2"
                   strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="16" rx="2" />
                <line x1="14" y1="4" x2="14" y2="20" />
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

        {/* (Body wrapper + old chat-column wrapper were removed 2026-05-17;
            toolbar is now inside the new chat-column wrapper above, so
            chat scrollback starts here as the toolbar's sibling.) */}
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
                  //
                  // Error UX (added 2026-05-16 after the "确认 button doesn't
                  // respond" report): the previous version silently swallowed
                  // mutateAsync failures, so a backend 500 / connection drop
                  // would look like "button is dead". We now surface the
                  // exception via the templateError state below.
                  <InitialTemplateChoice
                    isCreating={createSession.isPending}
                    error={templateError}
                    onConfirm={async (templateId) => {
                      setTemplateError("");
                      if (!selectedLlm) {
                        setTemplateError("请先在顶部下拉里选一个 LLM 提供方再点确认。");
                        return;
                      }
                      const fullLlmId = selectedModel
                        ? `${selectedLlm}:${selectedModel}`
                        : selectedLlm;
                      try {
                        const res = await createSession.mutateAsync({
                          llm_id: fullLlmId,
                          mode: "create",
                          template_id: templateId,
                        });
                        if (res.ok && res.data) {
                          const id = (res.data as { id: string }).id;
                          setActiveSession(id);
                        } else {
                          setTemplateError(
                            `后端拒绝创建会话：${(res as unknown as { error?: { message?: string } }).error?.message ?? "未知错误"}`,
                          );
                        }
                      } catch (err) {
                        const msg = err instanceof Error ? err.message : String(err);
                        setTemplateError(`创建会话失败：${msg}`);
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
                        // Assistant bubble follows the theme's --color-card
                        // (white in light mode, dark slate in dark mode);
                        // pure white was too harsh against the dark
                        // chat-column background. User bubble keeps the
                        // fixed WeChat-style green per spec b2d0e4a.
                        backgroundColor: msg.role === "user"
                          ? "#95EC69"
                          : "var(--color-card)",
                        color: msg.role === "user"
                          ? "#1F1F1F"
                          : "var(--color-ink)",
                        border: msg.role === "user"
                          ? undefined
                          : "1px solid var(--color-border-soft)",
                      }}
                    >
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    </div>
                  ))}

                  {/* Local user bubbles for messages still in the queue or
                      mid-flight. Cleared after the round's server invalidate
                      lands in the cache. Filtered to hide any whose content
                      already exists in rawMessages (otherwise the user's
                      message would briefly render twice — once persisted,
                      once still-pending). */}
                  {visiblePending.map((p) => (
                    <div
                      key={p.id}
                      className="mb-4 ml-auto max-w-[70%] rounded-xl px-4 py-2.5 text-sm leading-relaxed"
                      style={{ backgroundColor: "#95EC69", color: "#1F1F1F" }}
                    >
                      <div className="whitespace-pre-wrap">{p.content}</div>
                    </div>
                  ))}

                  {/* Unified thinking subframe — always opens while a round
                      is in flight (`chat.thinking`), so the user never
                      stares at a blank chat between sending and the first
                      reply. Body fills with three streams interleaved:
                        - inception.delta  (token-by-token from the LLM)
                        - inception.probe  (lifecycle checkpoints)
                        - plan_maker.sub_agent_io  (per-stage output)
                      If none have arrived yet, a placeholder line keeps
                      the panel visually anchored. Dark-mode safe via
                      --color-card-alt / --color-ink-muted tokens. */}
                  {(chat.thinking || streamingText) && (
                    <div
                      className="mb-4 mr-auto max-w-[85%] rounded-xl border p-3"
                      style={{
                        backgroundColor: "var(--color-card-alt)",
                        borderColor: "var(--color-border-soft)",
                      }}
                    >
                      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide"
                           style={{ color: "var(--color-ink-ghost)" }}>
                        <span className="flex gap-0.5">
                          <span className="h-1 w-1 animate-bounce rounded-full"
                                style={{ backgroundColor: "var(--color-brand-500)", animationDelay: "0ms" }} />
                          <span className="h-1 w-1 animate-bounce rounded-full"
                                style={{ backgroundColor: "var(--color-brand-500)", animationDelay: "150ms" }} />
                          <span className="h-1 w-1 animate-bounce rounded-full"
                                style={{ backgroundColor: "var(--color-brand-500)", animationDelay: "300ms" }} />
                        </span>
                        <span>Plan Maker 思考中</span>
                      </div>
                      <div
                        ref={streamBoxRef}
                        className="max-h-[8rem] overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed"
                        style={{ color: "var(--color-ink-muted)" }}
                      >
                        {streamingText || "等待 Plan Maker 响应…"}
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

          {/* Right panel — 3 explicit states per 2026-05-17 spec:
              (1) empty: nothing happening yet → empty center + hint
              (2) thinking: PMDebugLog (covers running / interrupted /
                  failed — failure_analysis + 从断点重来 already wired)
              (3) ready: TaskBlueprintEditor, OR "scheme lost" placeholder
                  if pmState says ready but draftBlueprint is gone
                  (history session opened without cached blueprint). */}
          {showRightPanel && (
            <div
              className="flex flex-col transition-all duration-200"
              style={{
                width: RIGHT_PANEL_WIDTH,
                flexShrink: 0,
                backgroundColor: "var(--color-surface)",
              }}
            >
              <div className="min-h-0 flex-1 p-4">
                {(() => {
                  const status = pmState.status;
                  // State 3: ready (or legacy iterate completion). Prefer
                  // the editable blueprint; fall back to "lost" notice
                  // when the data isn't on hand (e.g. user opened a
                  // historical session that wasn't saved as a project).
                  if (status === "ready") {
                    if (draftBlueprint) {
                      return (
                        <TaskBlueprintEditor
                          blueprint={draftBlueprint}
                          onChange={setDraftBlueprint}
                          onReEvaluate={() => {}}
                          reEvaluating={false}
                        />
                      );
                    }
                    return <BlueprintLostPanel />;
                  }
                  // State 2: thinking. running / interrupted / failed
                  // all map to the debug log; interrupted + failed get
                  // their own breakpoint affordance in the bottom bar.
                  if (
                    status === "running"
                    || status === "interrupted"
                    || status === "failed"
                  ) {
                    return <PMDebugLog state={pmState} />;
                  }
                  // Legacy iterate path: project already saved + edits
                  if (createdProjectId && draftBlueprint) {
                    return (
                      <TaskBlueprintEditor
                        blueprint={draftBlueprint}
                        onChange={setDraftBlueprint}
                        onReEvaluate={handleReEvaluate}
                        reEvaluating={reEvaluating}
                      />
                    );
                  }
                  // Drafting skeleton during create/iterate sub-agent
                  if (drafting) {
                    return <DraftingSkeleton mode={drafting.mode} />;
                  }
                  // State 1: empty — user manually opened the panel
                  // before any PM activity happened.
                  return <EmptyRightPanel />;
                })()}
              </div>
              <div
                className="px-4 py-3"
                style={{
                  backgroundColor: "var(--color-card)",
                  borderTop: "1px solid var(--color-border-soft)",
                }}
              >
                {/* PM v3 — buttons depend on cache status. status ===
                    'idle' falls through to legacy iterate path.
                    2026-05-17: when the right panel is open without any
                    PM activity AND no draftBlueprint (manual-toggle
                    empty state), hide the action bar entirely — there's
                    nothing to regenerate or save yet. */}
                {pmActive ? (
                  <PMActionButtons
                    state={pmState}
                    sessionId={activeSessionId}
                    editedBlueprint={draftBlueprint}
                    onSaved={() => {
                      // After save, drawer can close + redirect.
                      void qc.invalidateQueries({ queryKey: ["projects"] });
                      closeDrawer();
                      navigate("/");
                    }}
                    onChanged={() => { void refetchPmState(); }}
                  />
                ) : (createdProjectId && draftBlueprint) || drafting ? (
                  <div className="flex gap-2">
                    <button
                      onClick={handleRegenerate}
                      disabled={chat.thinking}
                      className="rounded-lg border px-3 py-2 text-xs font-medium transition-opacity hover:opacity-90 disabled:opacity-40"
                      style={{
                        backgroundColor: "var(--color-card)",
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
                ) : (
                  <div
                    className="text-center text-[11px]"
                    style={{ color: "var(--color-ink-faint)" }}
                  >
                    ← 在左侧输入创作思路开始
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/** PM v3 — bottom action bar driven by the draft cache status.
 *
 *  - status='running'    → Stop (calls /pm/cancel)
 *  - status='ready'      → 保存项目 (calls /pm/save)
 *  - status='failed'     → 从断点重来 (calls /pm/restart)
 *  - status='cancelled'  → 新建对话提示（用户应去 history dropdown 起新会话）
 */
function PMActionButtons({
  state,
  sessionId,
  editedBlueprint,
  onSaved,
  onChanged,
}: {
  state: PMState;
  sessionId: string | null;
  /** PM v3 — the inline TaskBlueprintEditor's current draft (potentially
   *  edited by the user). Forwarded as `override_blueprint` to the save
   *  endpoint so user edits are honoured instead of the cache version. */
  editedBlueprint?: Blueprint | null;
  onSaved: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function call(
    endpoint: string,
    label: string,
    body?: Record<string, unknown>,
  ): Promise<unknown> {
    if (!sessionId) return null;
    setBusy(true);
    try {
      const res = await apiFetch<unknown>(
        `/pm/sessions/${sessionId}/${endpoint}`,
        { method: "POST", body: JSON.stringify(body ?? {}) },
      );
      if (!res.ok) {
        const errMsg = res.ok ? "" : (res.error?.message ?? "未知错误");
        alert(`${label} 失败：${errMsg}`);
        return null;
      }
      return res.data;
    } catch (exc) {
      alert(`${label} 网络出错：${(exc as Error).message}`);
      return null;
    } finally {
      setBusy(false);
    }
  }

  if (state.status === "running") {
    // The chat composer (left column) already shows a red Stop button
    // while a round is in-flight — that's the same /pm/cancel call.
    // Repeating it here as 停止 PM 工作流 just made the bottom of the
    // panel feel cluttered. Show a thin hint instead so users still
    // discover where to cancel.
    return (
      <div
        className="flex items-center justify-center gap-2 text-[11px]"
        style={{ color: "var(--color-ink-faint)" }}
      >
        <span
          className="inline-block h-1.5 w-1.5 animate-pulse rounded-full"
          style={{ backgroundColor: "var(--color-brand-500)" }}
        />
        <span>工作流进行中 · 取消请用聊天框右下的「Stop」按钮</span>
      </div>
    );
  }

  if (state.status === "ready") {
    return (
      <button
        onClick={async () => {
          // Forward the (potentially edited) blueprint so user-side
          // tweaks in TaskBlueprintEditor are honoured. Backend uses
          // it instead of its cached version when provided.
          const body = editedBlueprint
            ? { override_blueprint: editedBlueprint }
            : undefined;
          const result = await call("save", "保存", body);
          if (result) onSaved();
        }}
        disabled={busy}
        className="flex w-full items-center justify-center gap-1 rounded-lg py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        style={{ backgroundColor: "var(--color-brand-500)" }}
      >
        {busy ? "保存中…" : "保存项目"}
      </button>
    );
  }

  if (state.status === "failed" || state.status === "interrupted") {
    // PM v3.1 (2026-05-17): 'interrupted' = backend was killed mid-run
    // (typically uvicorn --reload picking up a code change). Cache was
    // restored from disk on next boot but pm_task didn't resume — user
    // needs to click here to fire /pm/restart. Same code path as a
    // regular failed phase; backend uses `failed_phase` OR the last
    // completed phase as the resume point.
    const isInterrupted = state.status === "interrupted";
    const resumePoint = state.failed_phase
      ?? state.last_completed_phase
      ?? "?";
    return (
      <div className="flex flex-col gap-2">
        {isInterrupted ? (
          <div
            className="rounded-md px-2 py-1.5 text-[11px]"
            style={{
              backgroundColor: "rgba(245, 158, 11, 0.08)",
              border: "1px solid rgba(245, 158, 11, 0.3)",
              color: "#b45309",
            }}
          >
            ⚠️ 后端进程意外终止（dev 热重载或崩溃）— 草稿已从磁盘恢复，但 PM 工作流需手动继续。
          </div>
        ) : (
          <div
            className="rounded-md px-2 py-1.5 text-[11px]"
            style={{
              backgroundColor: "rgba(239, 68, 68, 0.08)",
              border: "1px solid rgba(239, 68, 68, 0.3)",
              color: "#b91c1c",
            }}
          >
            ⚠️ Phase「{resumePoint}」遇到问题（{state.error?.slice(0, 80) || "LLM 报错或关键 JSON 丢失"}）。请点下方重试。
          </div>
        )}
        <button
          onClick={async () => {
            await call("restart", "重来");
            onChanged();
          }}
          disabled={busy}
          className="flex-1 rounded-lg py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          style={{ backgroundColor: "#f59e0b" }}
          title={`从 phase '${resumePoint}' 重跑，上游产物从缓存复用`}
        >
          {busy ? "重来中…" : `从断点重来（${resumePoint}）`}
        </button>
      </div>
    );
  }

  if (state.status === "cancelled") {
    return (
      <div
        className="text-center text-xs"
        style={{ color: "var(--color-ink-muted)" }}
      >
        工作流已取消。点上方「新建对话」开启新一轮。
      </div>
    );
  }

  return null;
}

/** Human-readable labels for Plan Maker pipeline stages — used by the
 *  live thinking subframe to translate machine sub-agent names into
 *  Chinese reading easy for end users. */
const SUB_AGENT_LABELS: Record<string, string> = {
  compliance_gate: "合规审查",
  intent_classifier: "意图识别",
  create_new: "拆解新项目",
  iterate_existing: "规划迭代任务",
  clarify_design: "回答设计问题",
  modify_blueprint: "微调任务草稿",
  abort_or_restart: "中断/重置流程",
};

/** Right-panel skeleton shown while the create/iterate sub-agent is
 *  drafting the task list. Renders 3 shimmering task-pill placeholders
 *  + a header explaining what's happening, so the user has immediate
 *  visual feedback instead of staring at a chat-only column for 10-30s. */
function DraftingSkeleton({ mode }: { mode: "create" | "iterate" }) {
  const label = mode === "iterate" ? "正在规划迭代任务…" : "正在拆解项目任务…";
  return (
    <div className="flex h-full flex-col">
      <div
        className="mb-3 flex items-center gap-2 text-sm font-medium"
        style={{ color: "var(--color-ink-soft)" }}
      >
        <span className="inline-flex h-2 w-2 animate-pulse rounded-full"
              style={{ backgroundColor: "var(--color-brand-500)" }} />
        <span>{label}</span>
      </div>
      <div
        className="mb-3 text-[11px]"
        style={{ color: "var(--color-ink-ghost)" }}
      >
        Plan Maker 正在按你的需求设计任务图，完成后会在这里逐项填入。
      </div>
      <div className="flex-1 space-y-2 overflow-hidden">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="rounded-lg p-3"
            style={{
              backgroundColor: "var(--color-card-alt)",
              border: "1px solid var(--color-border-soft)",
              opacity: 1 - i * 0.18,
            }}
          >
            <div
              className="mb-2 h-3 w-3/4 animate-pulse rounded"
              style={{ backgroundColor: "var(--color-border-soft)" }}
            />
            <div
              className="h-2.5 w-1/2 animate-pulse rounded"
              style={{ backgroundColor: "var(--color-border-soft)",
                       animationDelay: `${i * 150}ms` }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

/** State 1 right-panel placeholder — shown when the user manually opened
 *  the panel via the top-bar toggle but no PM activity has happened yet.
 *  Center stays empty per spec; the bottom carries a gentle hint. */
function EmptyRightPanel() {
  return (
    <div className="flex h-full flex-col items-center justify-between py-8">
      <div />
      <div
        className="text-center text-[11px] leading-relaxed"
        style={{ color: "var(--color-ink-ghost)", maxWidth: "260px" }}
      >
        <div
          className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full"
          style={{
            backgroundColor: "var(--color-surface-alt)",
            color: "var(--color-ink-faint)",
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round">
            <polyline points="15 18 9 12 15 6" />
          </svg>
        </div>
        在左侧输入你的创作思路，Plan Maker 会在这里实时显示任务规划进度。
      </div>
    </div>
  );
}

/** State 3 fallback — pmState says ready but draftBlueprint is null
 *  (history session opened without cached blueprint, or PM cache was
 *  cleared after save). Center empty; bottom hint offers regenerate. */
function BlueprintLostPanel() {
  return (
    <div className="flex h-full flex-col items-center justify-between py-8">
      <div />
      <div
        className="text-center text-[11px] leading-relaxed"
        style={{ color: "var(--color-ink-ghost)", maxWidth: "280px" }}
      >
        <div
          className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full"
          style={{
            backgroundColor: "rgba(245, 158, 11, 0.12)",
            color: "#b45309",
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </div>
        <div className="mb-1" style={{ color: "var(--color-ink-muted)" }}>
          历史方案已丢失
        </div>
        在底部输入新的需求让 Plan Maker 重新生成，或从聊天框继续追问以恢复上下文。
      </div>
    </div>
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
    // Quiet "setup" checkpoints — they fire in <100ms and overwhelm the
    // user with noise. Keep the dev trace in console + LogDrawer; don't
    // render in the chat thinking subframe.
    case "enter":
    case "llm_resolved":
    case "llm_built":
    case "backstory_rendered":
    case "description_built":
    case "agent_and_task_built":
      return null;
    case "crew_built": return "▸ 开始推理";
    case "step": {
      const prev = s("preview").trim();
      const n = s("n");
      // Skip empty step probes (they're just heartbeats with no content).
      if (!prev) return null;
      return `▸ 第 ${n} 步：${prev}`;
    }
    case "kickoff_returned": return `✓ 推理完成（${s("steps")} 步）`;
    case "kickoff_timeout": return `⚠️ 超时（${s("timeout_s")}s）— 请检查 LLM 网络`;
    case "kickoff_failed": return `⚠️ 中断：${s("error")}`;
    case "salvage_persisted": return `✓ 已落盘 ${s("tasks")} 个任务`;
    case "early_exit_workflow_already_created": return null;
    // Result_unpacked is internal; sub_agent_io will surface the real output
    case "result_unpacked": return null;
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
  isCreating = false,
  error = "",
}: {
  onConfirm: (templateId: string) => void;
  /** Pending state of the upstream createSession mutation. While true,
   *  the ChoicePanel's 确认 button below is disabled with a spinner-ish
   *  label so a slow backend doesn't make the click look like a no-op. */
  isCreating?: boolean;
  /** Inline error rendered above the prompt — surfaces network /
   *  backend failures from the parent's mutateAsync. Empty string =
   *  no error banner. */
  error?: string;
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
        {error && (
          <div
            className="mb-3 rounded-md px-3 py-2 text-xs"
            style={{
              backgroundColor: "rgba(239, 68, 68, 0.10)",
              color: "#b91c1c",
              border: "1px solid rgba(239, 68, 68, 0.30)",
            }}
            role="alert"
          >
            {error}
          </div>
        )}
        <ChoicePanel
          prompt={
            isCreating
              ? "正在创建会话，请稍候…"
              : "你想做什么类型的 Unity 游戏？选一个模板，我会基于它的目录结构来设计任务。"
          }
          options={options}
          onConfirm={onConfirm}
          confirmDisabled={isCreating}
        />
      </div>
    </div>
  );
}

export default InceptionDrawer;
