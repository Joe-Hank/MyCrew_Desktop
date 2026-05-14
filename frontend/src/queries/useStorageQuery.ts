import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../net/api";

interface CategoryStat {
  bytes: number;
  rows?: number;
  files?: number;
}

export interface StorageUsage {
  non_system_total_bytes: number;
  breakdown: {
    projects_and_tasks: CategoryStat;
    inception_history: CategoryStat;
    events_log: CategoryStat;
    output_files: CategoryStat;
  };
  notes: string;
}

/** Storage stats for the Settings page footer widget. Refetches every
 *  60s — the value is just informational, not load-bearing. */
export function useStorageUsage() {
  return useQuery({
    queryKey: ["storage", "usage"],
    queryFn: async () => {
      const res = await apiFetch<StorageUsage>("/storage/usage");
      return res.data ?? null;
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}
