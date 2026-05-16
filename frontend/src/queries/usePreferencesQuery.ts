import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

// Preference rows are written as JSON. For the dismissible-dialog
// framework, the payload is { choice: string, dismissed_at: string }.
// Other future preference types can use different shapes — the cache
// stores arbitrary JSON-parsed values keyed by the storage key.
export type DismissedDialogValue = {
  choice: string;
  dismissed_at?: string;
};

export type PreferenceValue =
  | DismissedDialogValue
  | Record<string, unknown>
  | string
  | number
  | boolean
  | null;

const DISMISSED_DIALOG_PREFIX = "dismissed_dialog.";

export function dismissedDialogKey(dialogId: string): string {
  return `${DISMISSED_DIALOG_PREFIX}${dialogId}`;
}

/** Read every user preference in one shot. Loaded once at app start and
 *  cached — the dismissible-dialog hook resolves from this cache so we
 *  don't issue an HTTP round trip every time a confirm prompt opens. */
export function usePreferences() {
  return useQuery({
    queryKey: ["preferences"],
    queryFn: async () => {
      const res = await apiFetch<Record<string, PreferenceValue>>(
        "/preferences",
      );
      return res.data ?? {};
    },
    staleTime: 5 * 60_000,
  });
}

/** Upsert one preference. The dismissible-dialog flow uses this with the
 *  key `dismissed_dialog.<id>` and a DismissedDialogValue payload. */
export function useSetPreference() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      key,
      value,
    }: {
      key: string;
      value: PreferenceValue;
    }) =>
      apiFetch(`/preferences/${encodeURIComponent(key)}`, {
        method: "PUT",
        body: JSON.stringify({ value }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["preferences"] }),
  });
}

/** Reset a single preference — wired to the future "re-enable this
 *  prompt" button in Settings. */
export function useResetPreference() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (key: string) =>
      apiFetch(`/preferences/${encodeURIComponent(key)}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["preferences"] }),
  });
}
