import type { Task } from "../../queries/useProjectQuery";
import { useFailureAnalysis } from "../../queries/useWorkflowQuery";

/** Read-only failure diagnosis drawer (2026-05-17).
 *
 *  Replaces the chat-style AgentChatDrawer for failure-y tasks. The LLM
 *  has already written its diagnosis at the moment the task failed
 *  (backend/agents/failure_analyzer.py), so this drawer is a static
 *  render of `tasks.failure_analysis` plus the raw evidence
 *  (validation_errors + last_error) the model based it on.
 *
 *  States:
 *    - status='pending'   → analyzer hasn't finished yet; show a
 *                           spinner. The WS event task.failure_analyzed
 *                           triggers a query invalidation that flips
 *                           the view to 'ready'.
 *    - status='ready'     → render the markdown text.
 *    - status='not_failed'→ shouldn't happen (button is gated to
 *                           failure states); show fallback message.
 *    - HTTP error         → show the error inline.
 *
 *  AgentChatDrawer + the /workflow/tasks/{id}/guidance endpoint are
 *  kept in tree as a rollback path; this drawer is what the live button
 *  opens. */
function FailureAnalysisDrawer({
  task,
  onClose,
}: {
  task: Task;
  onClose: () => void;
}) {
  const { data, isLoading, error } = useFailureAnalysis(task.id);

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
          borderBottom: "1px solid var(--color-border-soft)",
          backgroundColor: "var(--color-surface)",
        }}
      >
        <div className="flex items-center gap-2">
          <span style={{ color: "#f59e0b" }}>📋</span>
          <span
            className="truncate text-sm font-semibold"
            style={{ color: "var(--color-ink-strong)" }}
            title={task.title}
          >
            失败原因 · {task.title || "未命名任务"}
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 transition-opacity hover:opacity-70"
          title="关闭"
          style={{ color: "var(--color-ink-muted)" }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {isLoading && <Pending message="正在加载诊断报告..." />}
        {!!error && <ErrorBox message={(error as Error).message} />}
        {data?.status === "pending" && (
          <Pending message="诊断助手正在分析这次失败（通常 5-15 秒）。完成后此处会自动刷新。" />
        )}
        {data?.status === "not_failed" && (
          <ErrorBox message="此任务当前不在失败状态——按钮显示是 bug，请刷新一下页面。" />
        )}
        {data?.status === "ready" && (
          <div className="flex flex-col gap-4">
            {/* The LLM output is structured Markdown (## 失败原因 / ##
                证据 / ## 怎么介入). Rendering as preformatted text gives
                a clean readable layout without pulling in a Markdown
                library — the headings are obvious from the ## prefix. */}
            <article
              className="rounded-lg p-3 text-[13px] leading-relaxed whitespace-pre-wrap"
              style={{
                backgroundColor: "var(--color-card)",
                border: "1px solid var(--color-border-soft)",
                color: "var(--color-ink-strong)",
                fontFamily: "inherit",
              }}
            >
              {data.text}
            </article>

            {data.at && (
              <div
                className="text-[10px]"
                style={{ color: "var(--color-ink-faint)" }}
              >
                诊断时间：{formatLocalTime(data.at)}
              </div>
            )}

            <Evidence
              validationErrors={data.validation_errors}
              lastError={data.last_error}
            />
          </div>
        )}
      </div>

      {/* Footer hint — no input field; this is read-only. */}
      <div
        className="px-4 py-2 text-[11px]"
        style={{
          borderTop: "1px solid var(--color-border-soft)",
          color: "var(--color-ink-faint)",
        }}
      >
        诊断为自动生成。按建议在 UI 上手动修，改完后回到任务卡点【重试】键。
      </div>
    </div>
  );
}

function Pending({ message }: { message: string }) {
  return (
    <div
      className="flex items-center gap-3 rounded-lg p-3 text-[12px]"
      style={{
        backgroundColor: "var(--color-card)",
        border: "1px dashed var(--color-border-soft)",
        color: "var(--color-ink-muted)",
      }}
    >
      <div
        className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-t-transparent"
        style={{
          borderColor: "var(--color-brand-500)",
          borderTopColor: "transparent",
        }}
      />
      <span>{message}</span>
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div
      className="rounded-lg p-3 text-[12px]"
      style={{
        backgroundColor: "rgba(239, 68, 68, 0.08)",
        border: "1px solid rgba(239, 68, 68, 0.3)",
        color: "#b91c1c",
      }}
    >
      {message}
    </div>
  );
}

function Evidence({
  validationErrors,
  lastError,
}: {
  validationErrors?: string | null;
  lastError?: string | null;
}) {
  // Parse validation_errors JSON if it's a string — backend stores it
  // as JSON-encoded array but legacy rows may already be parsed.
  let errs: string[] | null = null;
  if (validationErrors) {
    if (typeof validationErrors === "string") {
      try {
        const parsed = JSON.parse(validationErrors);
        if (Array.isArray(parsed)) errs = parsed.filter((x) => typeof x === "string");
      } catch {
        errs = [validationErrors];
      }
    }
  }

  const hasAny = (errs && errs.length > 0) || !!lastError;
  if (!hasAny) return null;

  return (
    <details
      className="rounded-lg p-3 text-[12px]"
      style={{
        backgroundColor: "var(--color-card)",
        border: "1px solid var(--color-border-soft)",
      }}
    >
      <summary
        className="cursor-pointer select-none font-medium"
        style={{ color: "var(--color-ink-soft)" }}
      >
        原始证据 (validation_errors / last_error)
      </summary>
      <div className="mt-2 flex flex-col gap-2">
        {errs && errs.length > 0 && (
          <div>
            <div
              className="mb-1 text-[10px] uppercase tracking-wide"
              style={{ color: "var(--color-ink-faint)" }}
            >
              validation_errors
            </div>
            <ul
              className="ml-4 list-disc text-[12px]"
              style={{ color: "var(--color-ink-soft)" }}
            >
              {errs.map((e, i) => (
                <li key={i} className="font-mono break-words">{e}</li>
              ))}
            </ul>
          </div>
        )}
        {lastError && (
          <div>
            <div
              className="mb-1 text-[10px] uppercase tracking-wide"
              style={{ color: "var(--color-ink-faint)" }}
            >
              last_error
            </div>
            <pre
              className="overflow-x-auto rounded p-2 text-[11px]"
              style={{
                backgroundColor: "var(--color-surface-alt)",
                color: "var(--color-ink-strong)",
                whiteSpace: "pre-wrap",
              }}
            >
              {lastError}
            </pre>
          </div>
        )}
      </div>
    </details>
  );
}

function formatLocalTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

export default FailureAnalysisDrawer;
