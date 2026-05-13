import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export interface UnityTemplate {
  id: string;
  label: string;
  description: string;
  render_pipeline: string;
  input_system: string;
  directory_skeleton: string[];
  default_packages: string[];
}

/** Read-only catalog of Unity templates served by GET /templates.
 *  Used by the Inception drawer to render the "pick template" cards. */
export function useTemplates() {
  return useQuery({
    queryKey: ["templates"],
    queryFn: async () => {
      const res = await apiFetch<UnityTemplate[]>("/templates");
      return res.data ?? [];
    },
    staleTime: 5 * 60 * 1000, // static catalog — refetch sparingly
  });
}
