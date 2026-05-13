import { useEffect, useRef } from "react";

const MIN_LINES = 3;
const MAX_LINES = 10;

interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  style?: React.CSSProperties;
}

/** Height-adaptive textarea: starts at 3 lines, grows to fit content, caps
 *  at 10 lines and scrolls beyond that. Used for large-text fields in the
 *  team / settings editor modals (goal, backstory, system prompt, etc.).
 *
 *  We measure scrollHeight on every value change and write the computed
 *  height back onto the element. `resize: none` prevents the user from
 *  manually dragging — the height is owned by content + the line cap. */
function AutoTextarea({ value, onChange, placeholder, className, style }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Reset to auto so we can shrink as well as grow.
    el.style.height = "auto";
    const cs = getComputedStyle(el);
    const lineHeight = parseFloat(cs.lineHeight) || 20;
    const padY =
      parseFloat(cs.paddingTop || "0") + parseFloat(cs.paddingBottom || "0");
    const borderY =
      parseFloat(cs.borderTopWidth || "0") + parseFloat(cs.borderBottomWidth || "0");
    const maxHeight = lineHeight * MAX_LINES + padY + borderY;
    const next = Math.min(el.scrollHeight, maxHeight);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [value]);

  return (
    <textarea
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={MIN_LINES}
      className={className}
      style={{ resize: "none", ...style }}
    />
  );
}

export default AutoTextarea;
