/**
 * Canonical "who runs this task" label resolution.
 *
 * Three places used to compute this independently (TaskNode for the
 * canvas, TaskBlueprintEditor for the inception draft preview,
 * ProjectCard's task pill on the home page). The first version of each
 * read only `agent_id`, which broke for PM v4 Crew tasks — their
 * agent_id column is null by design (workflow_svc routes through
 * _run_crew on performer_kind="crew"). After fixing each separately,
 * the three implementations drifted: different fallback strings, one
 * forgot the QA-Agent placeholder for final_qa, etc.
 *
 * Centralised here so the next "show me the performer" use site
 * doesn't repeat the same mistake. Return values:
 *   - Crew bound:    `Crew: <crew name>`
 *   - Crew bound but lookup miss:  `Crew: <id-suffix>`
 *   - Crew bound but no id:        `Crew: 待指定`
 *   - Single agent bound:          `<agent role>`
 *   - Agent bound but lookup miss: `<id-suffix>`
 *   - Unbound on a final_qa task:  `QA-Agent`
 *   - Unbound otherwise:           `待指定`
 */

interface AgentRow {
  id: string;
  role: string;
}

interface CrewRow {
  id: string;
  name: string;
}

interface TaskLike {
  performer_kind?: string | null;
  performer_id?: string | null;
  agent_id?: string | null;
  kind?: string;
}

export function performerLabel(
  task: TaskLike,
  pools: { agents?: readonly AgentRow[]; crews?: readonly CrewRow[] } = {},
): string {
  const kind = task.performer_kind;
  const pid = task.performer_id ?? task.agent_id;

  if (kind === "crew") {
    if (!pid) return "Crew: 待指定";
    const c = (pools.crews ?? []).find((x) => x.id === pid);
    return c ? `Crew: ${c.name}` : `Crew: ${pid.slice(-8)}`;
  }
  // performer_kind === "agent" or undefined (legacy / setup task)
  if (!pid) return task.kind === "final_qa" ? "QA-Agent" : "待指定";
  const a = (pools.agents ?? []).find((x) => x.id === pid);
  return a?.role ?? pid.slice(-8);
}
