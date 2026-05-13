import type { Task } from "../queries/useProjectQuery";

/** Build a `taskId → upstream-deps[]` adjacency map from a list of tasks.
 *  Cheap; the caller is expected to recompute when the task list changes. */
export function buildDepMap(tasks: Task[]): Map<string, string[]> {
  const m = new Map<string, string[]>();
  for (const t of tasks) m.set(t.id, t.deps ?? []);
  return m;
}

/** Returns true if adding edge `source → target` would introduce a cycle.
 *  Walks upwards from `source` through the dep map; if we encounter
 *  `target`, the cycle is real. Also forbids self-loops. */
export function wouldCreateCycle(
  source: string,
  target: string,
  depMap: Map<string, string[]>,
): boolean {
  if (source === target) return true;
  // BFS from source through its existing upstream deps. If target appears
  // among the ancestors of source, then source → target would close a loop.
  const visited = new Set<string>([source]);
  const queue: string[] = [source];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const upstream of depMap.get(cur) ?? []) {
      if (upstream === target) return true;
      if (!visited.has(upstream)) {
        visited.add(upstream);
        queue.push(upstream);
      }
    }
  }
  return false;
}
