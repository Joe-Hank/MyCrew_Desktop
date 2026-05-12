import { useEffect, useRef, useState } from "react";

export interface MenuAction {
  label: string;
  tone?: "default" | "danger" | "primary";
  disabled?: boolean;
  onClick: () => void;
}

/** Inline `⋯` button that pops up a vertical action menu on click. */
function RowActionsMenu({ actions }: { actions: MenuAction[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function close(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="rounded p-1 transition-colors hover:bg-zinc-100"
        style={{ color: "var(--color-ink-ghost)" }}
        aria-label="更多操作"
      >
        <svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor">
          <circle cx="3" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="13" cy="8" r="1.5" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute right-0 top-8 z-30 flex w-24 flex-col gap-1 rounded-lg bg-white p-1 shadow-lg"
          style={{ border: "1px solid var(--color-border-soft)" }}
        >
          {actions.map((a, i) => (
            <button
              key={i}
              disabled={a.disabled}
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                a.onClick();
              }}
              className="w-full rounded-md px-2 py-1.5 text-center text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-40"
              style={{
                backgroundColor:
                  a.tone === "danger" ? "#fda4af" : a.tone === "primary" ? "var(--color-brand-500)" : "transparent",
                color:
                  a.tone === "danger" || a.tone === "primary" ? "#ffffff" : "var(--color-ink-label)",
              }}
              onMouseEnter={(e) => {
                if (a.tone === "default" || !a.tone) {
                  e.currentTarget.style.backgroundColor = "var(--color-surface-alt)";
                }
              }}
              onMouseLeave={(e) => {
                if (a.tone === "default" || !a.tone) {
                  e.currentTarget.style.backgroundColor = "transparent";
                }
              }}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default RowActionsMenu;
