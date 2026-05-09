import { useState } from "react";
import type { Task } from "../../queries/useProjectQuery";

function AgentChatDrawer({
  task,
  onClose,
}: {
  task: Task;
  onClose: () => void;
}) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Array<{ role: "user" | "agent"; content: string }>>([
    {
      role: "agent",
      content: `任务「${task.title}」执行失败，状态: ${task.status}。请描述你希望如何调整或提供额外信息。`,
    },
  ]);

  function handleSend() {
    if (!input.trim()) return;
    const userMsg = input.trim();
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setInput("");
    // Placeholder: in Phase 7+ this will call the agent API
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        { role: "agent", content: `[Agent 回复占位] 已收到: "${userMsg}"` },
      ]);
    }, 500);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex h-full flex-col border-l border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-900">
      {/* Header */}
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

      {/* Messages */}
      <div className="flex-1 overflow-auto p-3">
        {messages.map((msg, i) => (
          <div
            key={i}
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
      </div>

      {/* Input */}
      <div className="border-t border-zinc-200 p-3 dark:border-zinc-700">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入反馈或指令..."
            rows={2}
            className="flex-1 resize-none rounded border border-zinc-300 px-3 py-1.5 text-xs dark:border-zinc-600 dark:bg-zinc-800"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="shrink-0 rounded bg-blue-500 px-3 text-xs font-medium text-white disabled:opacity-50"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}

export default AgentChatDrawer;
