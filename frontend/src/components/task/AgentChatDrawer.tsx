import { useCallback, useState } from "react";
import type { Task } from "../../queries/useProjectQuery";
import { useChatQueue } from "../../hooks/useChatQueue";

interface AgentMsg {
  id: string;
  role: "user" | "agent";
  content: string;
}

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
      content: `任务「${task.title}」执行失败，状态: ${task.status}。请描述你希望如何调整或提供额外信息。`,
    },
  ]);

  // Mock sender — Phase 7+ will replace this with a real Agent round-trip.
  // Routing through useChatQueue here is intentional: it gives the panel the
  // same queue-while-thinking UX as Plan Maker, so when the backend lands the
  // call site doesn't need to change.
  const sendAgentRound = useCallback(
    async (content: string, signal: AbortSignal): Promise<void> => {
      return new Promise<void>((resolve, reject) => {
        const id = `agent_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
        const t = setTimeout(() => {
          setMessages((prev) => [
            ...prev,
            { id: `${id}_user`, role: "user", content },
            { id, role: "agent", content: `[Agent 回复占位] 已收到: "${content}"` },
          ]);
          resolve();
        }, 600);
        signal.addEventListener("abort", () => {
          clearTimeout(t);
          const err = new Error("aborted");
          (err as Error & { name: string }).name = "AbortError";
          reject(err);
        });
      });
    },
    [],
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

  return (
    <div className="flex h-full flex-col border-l border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-700">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold">Agent 对话</span>
          <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800">
            {task.title}
          </span>
        </div>
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200">
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-auto p-3">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`mb-2.5 rounded-lg px-3 py-2 text-xs ${
              msg.role === "user"
                ? "ml-6 bg-blue-50 dark:bg-blue-950"
                : "mr-6 bg-zinc-100 dark:bg-zinc-800"
            }`}
          >
            <div className="mb-0.5 text-[10px] font-medium text-zinc-500">
              {msg.role === "user" ? "你" : "Agent"}
            </div>
            <div className="whitespace-pre-wrap">{msg.content}</div>
          </div>
        ))}
        {/* Local user bubbles for messages queued / mid-flight — same pattern
            as InceptionDrawer; collapse once the agent reply lands. */}
        {chat.pending.map((p) => (
          <div
            key={p.id}
            className="mb-2.5 ml-6 rounded-lg bg-blue-50 px-3 py-2 text-xs dark:bg-blue-950"
          >
            <div className="mb-0.5 text-[10px] font-medium text-zinc-500">你</div>
            <div className="whitespace-pre-wrap">{p.content}</div>
          </div>
        ))}
        {chat.thinking && (
          <div className="mb-2.5 mr-6 flex items-center gap-2 rounded-lg bg-zinc-100 px-3 py-2 text-xs dark:bg-zinc-800">
            <span className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500" style={{ animationDelay: "0ms" }} />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500" style={{ animationDelay: "150ms" }} />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-zinc-500" style={{ animationDelay: "300ms" }} />
            </span>
            <span>Agent 思考中...</span>
          </div>
        )}
      </div>

      <div className="border-t border-zinc-200 p-3 dark:border-zinc-700">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={chat.thinking ? "Agent 正在响应…继续输入会在本轮结束后一并发送" : "输入反馈或指令..."}
            rows={2}
            className="flex-1 resize-none rounded border border-zinc-300 px-3 py-1.5 text-xs dark:border-zinc-600 dark:bg-zinc-800"
          />
          {chat.thinking ? (
            <button
              onClick={handleStop}
              className="shrink-0 rounded bg-red-600 px-3 text-xs font-medium text-white"
            >
              停止
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="shrink-0 rounded bg-blue-500 px-3 text-xs font-medium text-white disabled:opacity-50"
            >
              发送
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentChatDrawer;
