import { useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

interface Props {
  prompt: string;
  /** Called after user enters/picks a path AND confirms. */
  onConfirm: (path: string) => void;
  readOnly?: boolean;
  confirmedPath?: string;
}

/** Path picker for iterate-mode root_path supply. Offers a text input
 *  and a native "Browse..." button via Tauri dialog. Two-step confirm
 *  matches ChoicePanel. */
function PathInputPanel({
  prompt, onConfirm, readOnly = false, confirmedPath,
}: Props) {
  const [path, setPath] = useState(confirmedPath ?? "");

  async function pickFolder() {
    try {
      const result = await openDialog({
        directory: true,
        multiple: false,
        title: "选择 Unity 项目根目录",
      });
      if (typeof result === "string") setPath(result);
    } catch {
      /* user cancelled or dialog plugin not loaded — fall through */
    }
  }

  if (readOnly) {
    return (
      <div
        className="rounded-lg p-3 text-xs"
        style={{
          backgroundColor: "var(--color-surface-alt)",
          border: "1px solid var(--color-border-soft)",
          color: "var(--color-ink-faint)",
        }}
      >
        <div className="mb-1 opacity-70">{prompt}</div>
        <div
          className="break-all font-mono"
          style={{ color: "var(--color-ink-soft)" }}
        >
          {confirmedPath}
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg p-4"
      style={{
        backgroundColor: "var(--color-card)",
        border: "1px solid var(--color-border-soft)",
      }}
    >
      <div
        className="mb-3 text-sm font-medium"
        style={{ color: "var(--color-ink-soft)" }}
      >
        {prompt}
      </div>

      <div className="flex gap-2">
        <input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="F:\UnityProjects\MyGame"
          className="flex-1 rounded-md px-2 py-1.5 font-mono text-xs outline-none"
          style={{
            backgroundColor: "var(--color-card-alt)",
            border: "1px solid var(--color-border-soft)",
            color: "var(--color-ink)",
          }}
        />
        <button
          onClick={pickFolder}
          className="rounded-md px-3 py-1.5 text-xs"
          style={{
            backgroundColor: "var(--color-card-alt)",
            border: "1px solid var(--color-border-soft)",
            color: "var(--color-ink-label)",
          }}
        >
          浏览…
        </button>
      </div>

      {path.trim() && (
        <div className="mt-3 flex justify-end">
          <button
            onClick={() => onConfirm(path.trim())}
            className="rounded-md px-4 py-1.5 text-xs font-medium text-white"
            style={{ backgroundColor: "var(--color-brand-500)" }}
          >
            确认
          </button>
        </div>
      )}
    </div>
  );
}

export default PathInputPanel;
