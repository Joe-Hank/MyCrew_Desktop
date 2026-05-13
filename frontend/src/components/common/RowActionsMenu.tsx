import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface MenuAction {
  label: string;
  tone?: "default" | "danger" | "primary";
  disabled?: boolean;
  onClick: () => void;
}

const MENU_WIDTH = 112;       // matches w-28 — slightly wider than old 96px for breathing room
const ESTIMATED_ROW_HEIGHT = 30;
const VERTICAL_GAP = 4;       // gap between trigger and menu

interface PortalPos {
  left: number;
  top: number;
  placement: "below" | "above";
}

/** Inline `⋯` button that pops up a vertical action menu on click.
 *
 *  The menu is rendered as a fixed-position portal at document.body so
 *  it can escape the table's `overflow-hidden` clipping. Placement
 *  auto-flips to "above" the trigger when the bottom-of-viewport space
 *  isn't enough to fit the menu height. */
function RowActionsMenu({ actions }: { actions: MenuAction[] }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<PortalPos | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Measure trigger + viewport when the menu opens, decide above vs below.
  useLayoutEffect(() => {
    if (!open || !triggerRef.current) {
      setPos(null);
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    const menuHeight = actions.length * ESTIMATED_ROW_HEIGHT + 8; // padding
    const spaceBelow = window.innerHeight - rect.bottom;
    const placement: "below" | "above" =
      spaceBelow >= menuHeight + VERTICAL_GAP ? "below" : "above";
    const top =
      placement === "below"
        ? rect.bottom + VERTICAL_GAP
        : rect.top - menuHeight - VERTICAL_GAP;
    // Right-align with the trigger button so the menu's right edge lines
    // up with the ⋯ icon — same horizontal feel as the original absolute
    // `right-0` anchoring inside a relative container.
    const left = Math.max(8, rect.right - MENU_WIDTH);
    setPos({ left, top, placement });
  }, [open, actions.length]);

  useEffect(() => {
    if (!open) return;
    function close(e: MouseEvent) {
      const t = e.target as Node;
      if (
        !triggerRef.current?.contains(t) &&
        !menuRef.current?.contains(t)
      ) {
        setOpen(false);
      }
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    // Close on scroll or resize so a stale-position menu doesn't drift.
    function onLayoutChange() {
      setOpen(false);
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onEsc);
    window.addEventListener("scroll", onLayoutChange, true);
    window.addEventListener("resize", onLayoutChange);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", onEsc);
      window.removeEventListener("scroll", onLayoutChange, true);
      window.removeEventListener("resize", onLayoutChange);
    };
  }, [open]);

  return (
    <>
      <button
        ref={triggerRef}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="rounded p-1 transition-colors hover:bg-zinc-100"
        style={{ color: "var(--color-ink-ghost)" }}
        aria-label="更多操作"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor">
          <circle cx="3" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="13" cy="8" r="1.5" />
        </svg>
      </button>

      {open && pos &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            className="fixed z-50 flex flex-col gap-1 rounded-lg p-1 shadow-lg"
            style={{
              left: pos.left,
              top: pos.top,
              width: MENU_WIDTH,
              backgroundColor: "var(--color-card)",
              border: "1px solid var(--color-border-soft)",
            }}
            onClick={(e) => e.stopPropagation()}
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
                    a.tone === "danger"
                      ? "#fda4af"
                      : a.tone === "primary"
                        ? "var(--color-brand-500)"
                        : "transparent",
                  color:
                    a.tone === "danger" || a.tone === "primary"
                      ? "#ffffff"
                      : "var(--color-ink-label)",
                }}
                onMouseEnter={(e) => {
                  if (a.tone === "default" || !a.tone) {
                    e.currentTarget.style.backgroundColor =
                      "var(--color-surface-alt)";
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
          </div>,
          document.body,
        )}
    </>
  );
}

export default RowActionsMenu;
