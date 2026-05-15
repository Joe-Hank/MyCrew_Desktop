import { useCallback, useEffect, useRef, useState } from "react";
import type { Task } from "../../queries/useProjectQuery";
import { useChatQueue } from "../../hooks/useChatQueue";
import { apiFetch } from "../../net/api";

interface AgentMsg {
  id: string;
  role: "user" | "agent";
  content: string;
}

/** Task-card → Agent chat drawer.
 *
 *  Visual language deliberately mirrors InceptionDrawer (Plan Maker chat):
 *    - User bubble: WeChat-style green (#95EC69, fixed across themes)
 *    - Agent bubble: var(--color-card) + soft border, dark-mode-safe
 *    - Surface uses --color-surface; borders use --color-border-soft
 *    - Brand-coloured "thinking" dots
 *    - Send button uses var(--color-brand-500)
 *
 *  Position is owned by TaskPage (right-side sibling of the canvas);
 *  this component only owns the inner layout. */
function AgentChatDrawer({
  task,
  onClose,
}: {
  task: Task;
  onClose: () => void;
}) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<AgentMsg[]>([
    {
      id: "intro",
      role: "agent",
      content:
        `我是 MyCrew 任务诊断助手——只解释「为什么这个任务没跑完」，` +
        `引导你在 UI 上手动修。改任务详情 / 重试 / 改 agent 都要你自己点。\n\n` +
        `当前任务：「${task.title}」，状态：${task.status}。问吧。`,
    },
  ]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Real guidance-agent round-trip. Backend endpoint is stateless:
  // each call sends ONE user message + the latest task snapshot the
  // server reads from DB; no history is persisted server-side, so
  // we just append the request + reply to local component state.
  const sendAgentRound = useCallback(
    async (content: string, signal: AbortSignal): Promise<void> => {
      const id = `agent_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      // Optimistically append the user bubble so it's visible immediately.
      setMessages((prev) => [...prev, { id: `${id}_user`, role: "user", content }]);

      try {
        const res = await apiFetch<{ reply: string }>(
          `/workflow/tasks/${task.id}/guidance`,
          {
            method: "POST",
            body: JSON.stringify({ message: content }),
            signal,
            // LLM call — opt out of the default 30s timeout.
            timeoutMs: 0,
          },
        );
        const reply = res.ok && res.data
          ? res.data.reply
          : `⚠️ 诊断助手暂时无法回复：${res.ok ? "无内容" : (res.error?.message ?? "未知错误")}`;
        setMessages((prev) => [...prev, { id, role: "agent", content: reply }]);
      } catch (err) {
        const name = (err as { name?: string })?.name;
        if (name === "AbortError") throw err;  // let useChatQueue handle
        const msg = err instanceof Error ? err.message : String(err);
        setMessages((prev) => [
          ...prev,
          { id, role: "agent", content: `⚠️ 网络出错：${msg}` },
        ]);
      }
    },
    [task.id],
  );
  const chat = useChatQueue({ send: sendAgentRound });

  function handleSend() {
    const content = input.trim();
    if (!content) return;
    setInput("");
    chat.enqueue(content);
  }

  function handleStop() {
    chat.stop();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // Auto-scroll to bottom on every new message / pending / thinking change.
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, chat.pending, chat.thinking]);

  // Dedupe local pending against persisted user bubbles already in `messages`
  // (mirrors the InceptionDrawer fix — prevents the green bubble from
  // briefly rendering twice during the round-trip).
  const recentUserContents = new Set(
    messages.filter((m) => m.role === "user").slice(-8).map((m) => m.content),
  );
  const visiblePending = chat.pending.filter((p) => !recentUserContents.has(p.content));

  return (
    <div
      className="flex h-full flex-col"
      style={{
        backgroundColor: "var(--color-surface)",
        borderLeft: "1px solid var(--color-border-soft)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{
          backgroundColor: "var(--color-card)",
          borderBottom: "1px solid var(--color-border-soft)",
        }}
      >
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="text-sm font-semibold"
            style={{ color: "var(--color-ink)" }}
          >
            Agent 对话
          </span>
          <span
            className="truncate rounded-md px-2 py-0.5 text-[10px]"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-muted)",
              maxWidth: "180px",
            }}
            title={task.title}
          >
            {task.title}
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 transition-colors hover:bg-zinc-100"
          style={{ color: "var(--color-ink-ghost)" }}
          aria-label="关闭"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      {/* Messages — same bubble language as InceptionDrawer */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-3">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`mb-3 max-w-[85%] rounded-xl px-3.5 py-2 text-sm leading-relaxed ${
              msg.role === "user" ? "ml-auto" : "mr-auto"
            }`}
            style={{
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
            <div className="whitespace-pre-wrap text-[13px]">{msg.content}</div>
          </div>
        ))}
        {visiblePending.map((p) => (
          <div
            key={p.id}
            className="mb-3 ml-auto max-w-[85%] rounded-xl px-3.5 py-2 text-sm leading-relaxed"
            style={{ backgroundColor: "#95EC69", color: "#1F1F1F" }}
          >
            <div className="whitespace-pre-wrap text-[13px]">{p.content}</div>
          </div>
        ))}
        {chat.thinking && (
          <div
            className="mb-3 mr-auto flex max-w-[85%] items-center gap-2 rounded-xl px-3.5 py-2 text-sm"
            style={{
              backgroundColor: "var(--color-card)",
              border: "1px solid var(--color-border-soft)",
              color: "var(--color-ink-muted)",
            }}
          >
            <span className="flex gap-1">
              <span
                className="h-1.5 w-1.5 animate-bounce rounded-full"
                style={{
                  backgroundColor: "var(--color-brand-500)",
                  animationDelay: "0ms",
                }}
              />
              <span
                className="h-1.5 w-1.5 animate-bounce rounded-full"
                style={{
                  backgroundColor: "var(--color-brand-500)",
                  animationDelay: "150ms",
                }}
              />
              <span
                className="h-1.5 w-1.5 animate-bounce rounded-full"
                style={{
                  backgroundColor: "var(--color-brand-500)",
                  animationDelay: "300ms",
                }}
              />
            </span>
            <span className="text-[12px]">Agent 思考中…</span>
          </div>
        )}
      </div>

      {/* Composer */}
      <div
        className="p-3"
        style={{
          backgroundColor: "var(--color-card)",
          borderTop: "1px solid var(--color-border-soft)",
        }}
      >
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              chat.thinking
                ? "Agent 正在响应…继续输入会在本轮结束后一并发送"
                : "输入反馈或指令…"
            }
            rows={2}
            className="flex-1 resize-none rounded-lg px-3 py-2 text-sm outline-none transition-colors focus:ring-1"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              border: "1px solid var(--color-border-soft)",
              color: "var(--color-ink)",
            }}
          />
          {chat.thinking ? (
            <button
              onClick={handleStop}
              className="flex h-9 shrink-0 items-center rounded-lg px-3 text-sm font-medium text-white transition-opacity hover:opacity-90"
              style={{ backgroundColor: "#dc2626" }}
            >
              停止
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="flex h-9 shrink-0 items-center gap-1 rounded-lg px-3 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              style={{ backgroundColor: "var(--color-brand-500)" }}
            >
              发送
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <line x1="12" y1="19" x2="12" y2="5" />
                <polyline points="5 12 12 5 19 12" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentChatDrawer;
