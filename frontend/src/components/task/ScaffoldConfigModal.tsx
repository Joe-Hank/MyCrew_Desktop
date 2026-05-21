import { useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

interface Props {
  /** Initial slug guess derived from project.name. Editable — user
   *  may want a different folder name than the display name. */
  defaultSlug: string;
  /** Already-picked parent if the user set one on the home card. */
  defaultParent: string;
  /** Title of the Unity template the project was created with, for
   *  display only (so the user knows what's being scaffolded). */
  templateLabel?: string;
  onSubmit: (args: { rootParentPath: string; slug: string }) => void;
  onCancel: () => void;
}

const SLUG_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

/** First-start config dialog for scaffolding flow (2026-05-17).
 *
 *  When a user kicks off a Unity-template project for the first time,
 *  the backend needs two inputs:
 *    1. parent directory (e.g. F:\UnityProjects\) — picked via native
 *       Tauri folder picker; manual text entry also accepted
 *    2. English slug — the on-disk folder name. We pre-fill it from the
 *       project's display name when that name is already ASCII-safe;
 *       otherwise the user types it themselves.
 *
 *  Closing the dialog without submitting leaves scaffold_status at
 *  'pending' — the user can re-trigger from the home card's 开始 button. */
function ScaffoldConfigModal({
  defaultSlug,
  defaultParent,
  templateLabel,
  onSubmit,
  onCancel,
}: Props) {
  const [slug, setSlug] = useState(defaultSlug || "");
  const [parent, setParent] = useState(defaultParent || "");
  const [pickInFlight, setPickInFlight] = useState(false);

  const slugOk = SLUG_RE.test(slug);
  const parentOk = parent.trim().length > 0;
  const canSubmit = slugOk && parentOk && !pickInFlight;

  // Esc closes
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  // No caller-supplied default and no previously-saved scaffold parent
  // — fall back to the OS desktop dir so the user isn't staring at an
  // empty field. Tauri's path API resolves it on Windows / macOS / Linux.
  useEffect(() => {
    if (parent) return;
    let cancelled = false;
    (async () => {
      try {
        const { desktopDir } = await import("@tauri-apps/api/path");
        const d = await desktopDir();
        if (!cancelled && d) setParent(d);
      } catch {
        // Non-Tauri / API missing — leave blank, user can type or browse.
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function pickFolder() {
    const hasTauri =
      typeof window !== "undefined" &&
      !!(window as unknown as { __TAURI_INTERNALS__?: unknown })
        .__TAURI_INTERNALS__;
    if (!hasTauri) {
      alert("非 Tauri 运行环境，无法调用系统文件选择器。请在输入框手动粘贴路径。");
      return;
    }
    setPickInFlight(true);
    try {
      const result = await openDialog({
        directory: true,
        multiple: false,
        title: "选择父目录（项目将被克隆到这个目录下）",
      });
      if (typeof result === "string") setParent(result);
    } catch (err) {
      alert(`系统文件选择器调用失败：${(err as Error).message}`);
    } finally {
      setPickInFlight(false);
    }
  }

  function handleSubmit() {
    if (!canSubmit) return;
    onSubmit({ rootParentPath: parent.trim(), slug: slug.trim() });
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
        <header className="mb-3 flex items-baseline justify-between">
          <h2
            className="text-base font-semibold"
            style={{ color: "var(--color-ink-strong)" }}
          >
            构建项目雏形
          </h2>
          {templateLabel && (
            <span
              className="rounded px-2 py-0.5 text-[10px]"
              style={{
                backgroundColor: "rgba(99, 102, 241, 0.14)",
                color: "#4f46e5",
              }}
            >
              {templateLabel}
            </span>
          )}
        </header>

        <p
          className="mb-4 text-[12px] leading-relaxed"
          style={{ color: "var(--color-ink-muted)" }}
        >
          首次启动会从模板仓库克隆一份干净的 Unity 项目到你指定的父目录下，
          以下面的英文名为新建文件夹名。之后这个新文件夹就是项目实际的根。
        </p>

        {/* English slug (folder name) */}
        <label
          className="mb-1 block text-[11px] font-medium"
          style={{ color: "var(--color-ink-soft)" }}
        >
          项目英文名（用作文件夹名）
        </label>
        <input
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder="如 PacMan、GoldMiner"
          className="mb-1 w-full rounded-md px-2 py-1.5 text-sm focus:outline-none"
          style={{
            backgroundColor: "var(--color-card-alt)",
            border: `1px solid ${slugOk || !slug
              ? "var(--color-border-soft)"
              : "#ef4444"}`,
            color: "var(--color-ink)",
            fontFamily: "ui-monospace, SFMono-Regular, monospace",
          }}
        />
        <div
          className="mb-4 text-[10px]"
          style={{
            color: slug && !slugOk ? "#b91c1c" : "var(--color-ink-faint)",
          }}
        >
          {slug && !slugOk
            ? "只允许 [A-Za-z0-9_-]，必须以字母或数字开头，不超过 64 字符"
            : "只允许字母、数字、_ 和 -；不允许空格或中文（Unity 与 Git 都更稳）"}
        </div>

        {/* Parent dir */}
        <label
          className="mb-1 block text-[11px] font-medium"
          style={{ color: "var(--color-ink-soft)" }}
        >
          父目录（项目会被克隆到这下面）
        </label>
        <div className="mb-1 flex gap-2">
          <input
            value={parent}
            onChange={(e) => setParent(e.target.value)}
            placeholder="如 F:\\UnityProjects"
            className="flex-1 rounded-md px-2 py-1.5 text-sm focus:outline-none"
            style={{
              backgroundColor: "var(--color-card-alt)",
              border: "1px solid var(--color-border-soft)",
              color: "var(--color-ink)",
              fontFamily: "ui-monospace, SFMono-Regular, monospace",
            }}
          />
          <button
            onClick={pickFolder}
            disabled={pickInFlight}
            className="rounded-md px-3 text-xs transition-colors disabled:opacity-50"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-muted)",
              border: "1px solid var(--color-border-soft)",
            }}
          >
            {pickInFlight ? "..." : "浏览"}
          </button>
        </div>
        <div
          className="mb-5 text-[10px]"
          style={{ color: "var(--color-ink-faint)" }}
        >
          {parent && slug
            ? <>最终项目根：<code style={{ color: "var(--color-brand-500)" }}>{parent}\{slug}</code></>
            : "选好后会显示最终路径预览"}
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-sm transition-colors"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-muted)",
              border: "1px solid var(--color-border-soft)",
            }}
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="rounded-md px-4 py-1.5 text-sm font-medium text-white transition-colors disabled:opacity-50"
            style={{ backgroundColor: "var(--color-brand-500)" }}
          >
            开始构建
          </button>
        </div>
      </div>
    </div>
  );
}

export default ScaffoldConfigModal;
