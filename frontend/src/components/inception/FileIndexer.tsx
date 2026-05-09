import { useState } from "react";
import { apiFetch } from "../../net/api";

interface IndexedPath {
  path: string;
  totalFiles: number;
  totalBytes: number;
  strategy: string;
}

function FileIndexer({
  sessionId,
  indexed,
  onAdd,
  onRemove,
}: {
  sessionId: string;
  indexed: IndexedPath[];
  onAdd: (entry: IndexedPath) => void;
  onRemove: (path: string) => void;
}) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleAdd() {
    if (!input.trim()) return;
    setLoading(true);
    try {
      const res = await apiFetch<{
        path: string;
        total_files: number;
        total_bytes: number;
        strategy: string;
      }>("/files/index", {
        method: "POST",
        body: JSON.stringify({ path: input.trim() }),
      });
      if (res.ok && res.data) {
        onAdd({
          path: res.data.path,
          totalFiles: res.data.total_files,
          totalBytes: res.data.total_bytes,
          strategy: res.data.strategy,
        });
        // Also register with inception session
        await apiFetch(`/inceptions/sessions/${sessionId}/index`, {
          method: "POST",
          body: JSON.stringify({ path: input.trim() }),
        });
        setInput("");
      }
    } finally {
      setLoading(false);
    }
  }

  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  }

  return (
    <div className="space-y-2">
      {indexed.length > 0 && (
        <div className="space-y-1">
          {indexed.map((entry) => (
            <div
              key={entry.path}
              className="flex items-center justify-between rounded bg-zinc-100 px-2 py-1 text-[11px] dark:bg-zinc-800"
            >
              <div className="flex items-center gap-1.5 truncate">
                <span className={`rounded px-1 py-0.5 text-[9px] font-medium ${
                  entry.strategy === "inline"
                    ? "bg-green-100 text-green-600 dark:bg-green-900 dark:text-green-300"
                    : "bg-yellow-100 text-yellow-600 dark:bg-yellow-900 dark:text-yellow-300"
                }`}>
                  {entry.strategy === "inline" ? "全文" : "按需"}
                </span>
                <span className="truncate" title={entry.path}>{entry.path}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-zinc-400">
                  {entry.totalFiles}文件 {formatBytes(entry.totalBytes)}
                </span>
                <button
                  onClick={() => onRemove(entry.path)}
                  className="text-zinc-400 hover:text-red-500"
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-1.5">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          className="flex-1 rounded border border-zinc-300 px-2 py-1 text-xs dark:border-zinc-600 dark:bg-zinc-800"
          placeholder="输入文件/目录路径..."
        />
        <button
          onClick={handleAdd}
          disabled={!input.trim() || loading}
          className="shrink-0 rounded border border-zinc-300 px-2 py-1 text-xs transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-600 dark:hover:bg-zinc-800"
        >
          {loading ? "..." : "索引"}
        </button>
      </div>
    </div>
  );
}

export default FileIndexer;
export type { IndexedPath };
