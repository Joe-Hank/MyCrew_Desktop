import { useState } from "react";

interface Props {
  /** Relative paths from audit_against_skeleton() that were expected
   *  to exist but didn't. UI shows them verbatim. */
  missing: string[];
  /** Where the (broken) scaffold lives, for display only. */
  rootPath?: string | null;
  /** Trigger destructive overwrite re-clone. Returns once the request
   *  is queued — actual progress streams via WS. */
  onRepair: () => Promise<void>;
  onCancel: () => void;
}

/** Pops on the user's first 「开始」 click if the audit finds critical
 *  paths missing from a previously-scaffolded project root (git clone
 *  truncated, user manually deleted something, antivirus quarantined,
 *  etc).
 *
 *  Two-step confirmation: user must check the "我了解会覆盖" checkbox
 *  before the 「一键修复」 button enables. Mirrors the destructive-
 *  action UX pattern used elsewhere (e.g. project delete confirm). */
function ScaffoldAuditModal({ missing, rootPath, onRepair, onCancel }: Props) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [pending, setPending] = useState(false);

  async function handleRepair() {
    if (!acknowledged || pending) return;
    setPending(true);
    try {
      await onRepair();
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.45)" }}
      onClick={onCancel}
    >
      <div
        className="w-full max-w-[480px] rounded-xl p-5 shadow-2xl"
        style={{
          backgroundColor: "var(--color-card)",
          border: "1px solid var(--color-border-soft)",
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
      >
        <header className="mb-3 flex items-center gap-2">
          <span style={{ color: "#f59e0b" }}>⚠️</span>
          <h2
            className="text-base font-semibold"
            style={{ color: "var(--color-ink-strong)" }}
          >
            项目结构损坏
          </h2>
        </header>

        <p
          className="mb-3 text-[12px] leading-relaxed"
          style={{ color: "var(--color-ink-muted)" }}
        >
          检查发现模板克隆后的项目根目录缺少关键文件 / 目录。可能原因：
          git 下载中断、用户手动删除、杀软隔离等。
        </p>

        {rootPath && (
          <div
            className="mb-3 rounded p-2 text-[11px]"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-faint)",
              fontFamily: "ui-monospace, SFMono-Regular, monospace",
            }}
            title={rootPath}
          >
            根目录：{rootPath}
          </div>
        )}

        <div className="mb-3">
          <div
            className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--color-ink-ghost)" }}
          >
            缺失的关键路径
          </div>
          <ul
            className="rounded p-2 text-[12px]"
            style={{
              backgroundColor: "rgba(245, 158, 11, 0.08)",
              border: "1px solid rgba(245, 158, 11, 0.3)",
              color: "#b45309",
              fontFamily: "ui-monospace, SFMono-Regular, monospace",
            }}
          >
            {missing.map((m) => (
              <li key={m}>· {m}</li>
            ))}
          </ul>
        </div>

        <label
          className="mb-4 flex items-start gap-2 text-[12px] leading-relaxed"
          style={{ color: "var(--color-ink-soft)" }}
        >
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            我了解【一键修复】会
            <strong style={{ color: "#b91c1c" }}>完全删除并重新下载</strong>
            该目录，任何手动修改（包括 Assets/ 下添加的资源）都会丢失。
          </span>
        </label>

        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={pending}
            className="rounded-md px-3 py-1.5 text-sm transition-colors disabled:opacity-50"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-muted)",
              border: "1px solid var(--color-border-soft)",
            }}
          >
            取消
          </button>
          <button
            onClick={handleRepair}
            disabled={!acknowledged || pending}
            className="rounded-md px-4 py-1.5 text-sm font-medium text-white transition-opacity disabled:opacity-50"
            style={{ backgroundColor: "#dc2626" }}
          >
            {pending ? "正在重新下载…" : "一键修复（覆盖重下）"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ScaffoldAuditModal;
