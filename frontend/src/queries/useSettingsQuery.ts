import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export type ComplianceMode = "free" | "harmonious";

interface ComplianceModeRes {
  mode: ComplianceMode;
}

/** Read the app-wide compliance mode (free | harmonious). Backs the
 *  PermissionTable toggle that gates whether Plan Maker refuses
 *  potentially-violating content. */
export function useComplianceMode() {
  return useQuery({
    queryKey: ["settings", "compliance-mode"],
    queryFn: async () => {
      const res = await apiFetch<ComplianceModeRes>("/settings/compliance-mode");
      return (res.data?.mode ?? "free") as ComplianceMode;
    },
    staleTime: 60_000,
  });
}

export function useSetComplianceMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: ComplianceMode) =>
      apiFetch("/settings/compliance-mode", {
        method: "PUT",
        body: JSON.stringify({ mode }),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["settings", "compliance-mode"] }),
  });
}
