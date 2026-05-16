/**
 * Topological wave ordering for task lists.
 *
 * Two surfaces need to show the same ordering or users get confused:
 *   - The canvas (CanvasBlueprint) lays nodes out in topological waves
 *     left → right, top → bottom within a wave.
 *   - The home-card task list (ProjectCard.TaskPill grid) used to render
 *     in DB insertion order, which meant "Task #1" on the home card
 *     could be the canvas's last node (post-2026-05-16 audit: 2D 美术资产
 *     was at DB index 9 but at canvas wave 1 because it only depends on
 *     the setup task).
 *
 * This helper produces a stable list of tasks sorted as:
 *   wave 0 task 0, wave 0 task 1, ..., wave 1 task 0, ...
 * Within a wave the original (DB) order is preserved so consecutive
 * runs on the same data return the same sequence.
 */

interface TaskLike {
  id: string;
  deps?: readonly string[] | null;
}

export function topoOrder<T extends TaskLike>(tasks: readonly T[]): T[] {
  const placed = new Set<string>();
  const out: T[] = [];

  for (let safety = 0; safety < tasks.length; safety++) {
    const wave: T[] = [];
    for (const t of tasks) {
      if (placed.has(t.id)) continue;
      if ((t.deps ?? []).every((d) => placed.has(d))) wave.push(t);
    }
    if (wave.length === 0) break;
    for (const t of wave) placed.add(t.id);
    out.push(...wave);
  }
  // Tail-end safety: any task whose deps still aren't satisfied
  // (orphan dep referring to a deleted task, or a cycle) goes to the
  // bottom in DB order so the user can still see them.
  for (const t of tasks) {
    if (!placed.has(t.id)) out.push(t);
  }
  return out;
}
