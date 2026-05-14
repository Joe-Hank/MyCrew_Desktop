interface Tab<K extends string> {
  key: K;
  label: string;
  count?: number;
}

/** Pill-style tab group used on Team & Settings pages. */
function PillTabs<K extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: Tab<K>[];
  active: K;
  onChange: (k: K) => void;
}) {
  return (
    <div
      className="inline-flex items-center gap-1 rounded-full p-1"
      style={{ backgroundColor: "var(--color-surface-alt)" }}
    >
      {tabs.map((t) => {
        const isActive = t.key === active;
        return (
          <button
            key={t.key}
            onClick={() => onChange(t.key)}
            className="rounded-full px-4 py-1.5 text-sm font-medium transition-all"
            style={{
              // Was hardcoded "white" — looked jarring in dark mode because
              // the slider stayed pure white against the dark page chrome.
              // var(--color-card) is theme-aware (white in light mode,
              // proper dark surface in dark mode), matching the card +
              // modal surfaces.
              backgroundColor: isActive ? "var(--color-card)" : "transparent",
              color: isActive ? "var(--color-brand-500)" : "var(--color-ink-muted)",
              boxShadow: isActive ? "0 1px 2px rgba(0, 0, 0, 0.06)" : "none",
            }}
          >
            {t.label}
            {typeof t.count === "number" && (
              <span className="ml-0.5">（{t.count}）</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default PillTabs;
