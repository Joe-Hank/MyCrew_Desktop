interface QueryErrorStateProps {
  title: string;
  error: unknown;
  onRetry: () => void;
  isFetching?: boolean;
}

function QueryErrorState({ title, error, onRetry, isFetching }: QueryErrorStateProps) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div
      className="rounded-xl p-6 text-sm"
      style={{
        border: "1px solid rgba(239,68,68,0.25)",
        backgroundColor: "rgba(239,68,68,0.06)",
        color: "var(--color-ink)",
      }}
    >
      <div className="mb-2 font-medium">{title}</div>
      <div className="mb-3 break-words text-xs" style={{ color: "var(--color-ink-faint)" }}>
        {msg}
      </div>
      <div className="text-xs" style={{ color: "var(--color-ink-faint)" }}>
        数据未丢失，仍在本地数据库中。请确认后端进程是否运行，然后点击重试。
      </div>
      <button
        onClick={onRetry}
        disabled={isFetching}
        className="mt-3 rounded-lg px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
        style={{ backgroundColor: "var(--color-brand-500)" }}
      >
        {isFetching ? "重试中…" : "重试"}
      </button>
    </div>
  );
}

export default QueryErrorState;
