import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

export interface AgentRow {
  id: string;
  role: string;
  goal: string | null;
  backstory: string | null;
  llm_id: string | null;
  is_auto_generated: number;
}

/** List of agents the user can pick as task executors. Plan Maker and other
 *  auto-generated meta-agents are filtered out — they shouldn't be assigned
 *  as task runners. */
export function useAssignableAgents() {
  return useQuery({
    queryKey: ["agents", "assignable"],
    queryFn: async () => {
      const res = await apiFetch<AgentRow[]>("/agents");
      const all = res.data ?? [];
      return all.filter((a) => !a.is_auto_generated);
    },
  });
}
