import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  dismissedDialogKey,
  usePreferences,
  useSetPreference,
  type DismissedDialogValue,
} from "../../queries/usePreferencesQuery";

// ── Public types ───────────────────────────────────────────────────

export interface ConfirmOption {
  /** Stable identifier returned to the caller and persisted in
   *  user_preferences when "不再显示" is ticked. Use short snake_case
   *  values like `cleanup`, `keep`, `cancel`. */
  value: string;
  label: string;
  /** Highlight this option as the recommended action (one only). */
  primary?: boolean;
  /** Tone-marks the option. `danger` paints the button red; `subtle`
   *  draws it as a plain link-style fallback. */
  tone?: "primary" | "danger" | "subtle";
}

export interface ConfirmRequest {
  /** Required when `allowDismiss` is true — names this dialog in
   *  user_preferences. Convention: dot-separated namespace, e.g.
   *  `retry.cleanup_artifacts`. */
  dialogId?: string;
  title: string;
  /** Markdown not supported on purpose — keep messages short and
   *  literal so the modal stays one screen. Newlines OK. */
  body?: ReactNode;
  options: ConfirmOption[];
  /** Show the "不再显示" checkbox. Requires dialogId. The dismissed
   *  choice is what the user clicked when they ticked the box; future
   *  calls auto-resolve to it. */
  allowDismiss?: boolean;
}

export type ConfirmResult = {
  /** The chosen option's `value`, or `null` when the user cancelled by
   *  pressing ESC / clicking the backdrop. */
  choice: string | null;
  /** True iff the dialog was skipped because the user previously ticked
   *  "不再显示". Lets callers log a hint or show a subtle toast. */
  autoResolved: boolean;
};

// ── Internal state held by the provider ──────────────────────────

interface PendingDialog extends ConfirmRequest {
  resolve: (result: ConfirmResult) => void;
}

interface ConfirmContextValue {
  open: (req: ConfirmRequest) => Promise<ConfirmResult>;
}

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

// ── Provider — mount once at app root ────────────────────────────

export function ConfirmDialogProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingDialog | null>(null);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const { data: preferences } = usePreferences();
  const setPreference = useSetPreference();
  const closeRef = useRef<((r: ConfirmResult) => void) | null>(null);

  const open = useCallback(
    (req: ConfirmRequest): Promise<ConfirmResult> => {
      // Auto-resolve if the user previously dismissed this dialog with a
      // specific choice — but only when allowDismiss + dialogId were
      // provided (otherwise we don't know what to look up).
      if (req.allowDismiss && req.dialogId && preferences) {
        const stored = preferences[
          dismissedDialogKey(req.dialogId)
        ] as DismissedDialogValue | undefined;
        const choice = stored?.choice;
        if (
          typeof choice === "string" &&
          req.options.some((o) => o.value === choice)
        ) {
          return Promise.resolve({ choice, autoResolved: true });
        }
      }
      return new Promise<ConfirmResult>((resolve) => {
        setDontShowAgain(false);
        setPending({ ...req, resolve });
        closeRef.current = resolve;
      });
    },
    [preferences],
  );

  const close = useCallback(
    (choice: string | null) => {
      const dlg = pending;
      if (!dlg) return;
      // Only persist the dismissed-choice when the user actually picked
      // an option (not when they cancelled with ESC) and the dialog is
      // dismissible. Cancelling never trains the dismiss state.
      if (
        choice !== null &&
        dontShowAgain &&
        dlg.allowDismiss &&
        dlg.dialogId
      ) {
        setPreference.mutate({
          key: dismissedDialogKey(dlg.dialogId),
          value: {
            choice,
            dismissed_at: new Date().toISOString(),
          },
        });
      }
      setPending(null);
      setDontShowAgain(false);
      dlg.resolve({ choice, autoResolved: false });
    },
    [pending, dontShowAgain, setPreference],
  );

  useEffect(() => {
    if (!pending) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [pending, close]);

  const ctxValue = useMemo<ConfirmContextValue>(() => ({ open }), [open]);

  return (
    <ConfirmContext.Provider value={ctxValue}>
      {children}
      {pending && (
        <ConfirmDialogView
          request={pending}
          dontShowAgain={dontShowAgain}
          onDontShowAgainChange={setDontShowAgain}
          onChoose={close}
        />
      )}
    </ConfirmContext.Provider>
  );
}

// ── The modal itself ────────────────────────────────────────────

function ConfirmDialogView({
  request,
  dontShowAgain,
  onDontShowAgainChange,
  onChoose,
}: {
  request: ConfirmRequest;
  dontShowAgain: boolean;
  onDontShowAgainChange: (v: boolean) => void;
  onChoose: (choice: string | null) => void;
}) {
  const showDismiss = Boolean(request.allowDismiss && request.dialogId);
  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.45)" }}
      onClick={() => onChoose(null)}
      role="presentation"
    >
      <div
        className="flex w-[440px] max-w-[92vw] flex-col rounded-xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={request.title}
      >
        <div className="border-b px-5 py-4">
          <h3 className="text-base font-semibold text-gray-900">
            {request.title}
          </h3>
        </div>
        {request.body && (
          <div className="px-5 py-4 text-sm leading-relaxed text-gray-700">
            {request.body}
          </div>
        )}
        {showDismiss && (
          <label className="flex items-center gap-2 px-5 pb-3 text-xs text-gray-500">
            <input
              type="checkbox"
              checked={dontShowAgain}
              onChange={(e) => onDontShowAgainChange(e.target.checked)}
            />
            不再显示此提示（仍可在设置中重置）
          </label>
        )}
        <div className="flex flex-row-reverse flex-wrap gap-2 border-t bg-gray-50 px-5 py-3">
          {request.options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChoose(opt.value)}
              className={buttonClass(opt)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function buttonClass(opt: ConfirmOption): string {
  const base =
    "min-w-[88px] rounded-md px-3 py-1.5 text-sm font-medium transition-colors";
  if (opt.tone === "danger") {
    return `${base} bg-red-600 text-white hover:bg-red-700`;
  }
  if (opt.tone === "subtle") {
    return `${base} text-gray-600 hover:bg-gray-200`;
  }
  if (opt.primary || opt.tone === "primary") {
    return `${base} bg-indigo-600 text-white hover:bg-indigo-700`;
  }
  return `${base} border border-gray-300 bg-white text-gray-800 hover:bg-gray-100`;
}

// ── Hooks ─────────────────────────────────────────────────────────

/** Imperative confirm API. Returns a Promise that resolves with the
 *  chosen option's `value`, or `null` if cancelled. Auto-resolves when
 *  the user previously ticked "不再显示".
 *
 *  Bind a stable dialogId per call site so the dismiss state targets
 *  the right dialog:
 *
 *      const confirm = useDismissibleConfirm()
 *      const r = await confirm({
 *        dialogId: 'retry.cleanup_artifacts',
 *        title: '...',
 *        options: [...],
 *        allowDismiss: true,
 *      })
 *      if (r.choice === 'cleanup') { ... }
 */
export function useDismissibleConfirm() {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    throw new Error(
      "useDismissibleConfirm must be used inside <ConfirmDialogProvider>",
    );
  }
  return ctx.open;
}
