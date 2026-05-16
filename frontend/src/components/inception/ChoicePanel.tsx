import { useState } from "react";

export interface ChoiceOption {
  value: string;
  label: string;
  description?: string;
}

interface Props {
  prompt: string;
  options: ChoiceOption[];
  /** Called only after user clicks "确认". Card click alone just previews. */
  onConfirm: (value: string) => void;
  /** Once confirmed the panel turns to a read-only history bubble. */
  readOnly?: boolean;
  confirmedValue?: string;
  /** Lock the 确认 button (e.g. while the upstream createSession
   *  mutation is in flight). Card preview still works so the user can
   *  switch their pick while waiting. */
  confirmDisabled?: boolean;
}

/** Two-step card selector: click to preview → "确认" button appears →
 *  click confirm to lock in. Used by Plan Maker's first-turn mode picker
 *  and the template-selection step. */
function ChoicePanel({
  prompt, options, onConfirm, readOnly = false, confirmedValue,
  confirmDisabled = false,
}: Props) {
  const [selected, setSelected] = useState<string | null>(
    confirmedValue ?? null,
  );

  if (readOnly) {
    const confirmed = options.find((o) => o.value === confirmedValue);
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
        <div style={{ color: "var(--color-ink-soft)" }}>
          已选：<span className="font-medium">{confirmed?.label ?? confirmedValue}</span>
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

      <div className="grid grid-cols-2 gap-2">
        {options.map((opt) => {
          const isSelected = selected === opt.value;
          return (
            <button
              key={opt.value}
              onClick={() => setSelected(opt.value)}
              className="rounded-md p-3 text-left text-xs transition-all"
              style={{
                backgroundColor: isSelected
                  ? "var(--color-brand-500)"
                  : "var(--color-card-alt)",
                color: isSelected ? "#ffffff" : "var(--color-ink-label)",
                border: isSelected
                  ? "1px solid var(--color-brand-500)"
                  : "1px solid var(--color-border-soft)",
                boxShadow: isSelected
                  ? "0 0 0 3px rgba(12, 140, 233, 0.18)"
                  : "none",
              }}
            >
              <div className="mb-1 text-sm font-semibold">{opt.label}</div>
              {opt.description && (
                <div
                  className="text-[11px] leading-snug"
                  style={{ opacity: isSelected ? 0.92 : 0.65 }}
                >
                  {opt.description}
                </div>
              )}
            </button>
          );
        })}
      </div>

      {selected && (
        <div className="mt-3 flex justify-end">
          <button
            onClick={() => onConfirm(selected)}
            disabled={confirmDisabled}
            className="rounded-md px-4 py-1.5 text-xs font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
            style={{ backgroundColor: "var(--color-brand-500)" }}
          >
            {confirmDisabled ? "处理中…" : "确认"}
          </button>
        </div>
      )}
    </div>
  );
}

export default ChoicePanel;
