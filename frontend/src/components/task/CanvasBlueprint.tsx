import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  addEdge,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type EdgeChange,
} from "@xyflow/react";
import type { Task } from "../../queries/useProjectQuery";
import {
  useUpdateTask,
  useCreateTask,
  useDeleteTask,
} from "../../queries/useWorkflowQuery";
import { useThemeStore } from "../../stores/useThemeStore";
import { buildDepMap, wouldCreateCycle } from "../../lib/depCycle";
import CanvasTaskNode, { type CanvasTaskNodeData } from "./CanvasTaskNode";
import type { TaskAction } from "./TaskNode";

// ── Auto-layout fallback for tasks with no persisted position ──────
//
// Each task gets initial coordinates from a topological wave layout (same
// shape the old <Blueprint/> rendered): waves run left→right, tasks in the
// same wave stack top→bottom. NULL position_x/position_y on the DB row
// means "never been dragged" → use this fallback. Once the user drags a
// node, its individual position gets persisted.
// Auto-layout spacing. COL_W: horizontal stride between dependency waves
// (left → right). ROW_H: vertical stride between parallel tasks within the
// same wave. Tuned generously (per user feedback) so cards with multi-line
// detail text don't visually overlap and the dependency curves have room
// to flow without crossing card bodies.
const COL_W = 340;
// ROW_H tuned 2026-05-15: was 330, dropped to 250 per user feedback that
// the default vertical stride felt too loose (-80px). Cards still fit
// agent row + status indicator + room for the amber failure badge.
const ROW_H = 250;

function computeAutoLayout(tasks: Task[]): Map<string, { x: number; y: number }> {
  const placed = new Set<string>();
  const waves: Task[][] = [];
  for (let safety = 0; safety < tasks.length; safety++) {
    const wave: Task[] = [];
    for (const t of tasks) {
      if (placed.has(t.id)) continue;
      if ((t.deps ?? []).every((d) => placed.has(d))) wave.push(t);
    }
    if (wave.length === 0) break;
    for (const t of wave) placed.add(t.id);
    waves.push(wave);
  }
  // Cycle/orphan safety: any tasks still unplaced go in a tail wave
  const leftover = tasks.filter((t) => !placed.has(t.id));
  if (leftover.length) waves.push(leftover);

  const pos = new Map<string, { x: number; y: number }>();
  waves.forEach((wave, wi) => {
    wave.forEach((t, ti) => {
      pos.set(t.id, { x: 40 + wi * COL_W, y: 40 + ti * ROW_H });
    });
  });
  return pos;
}

// ── Component ──────────────────────────────────────────────────────

const nodeTypes = { task: CanvasTaskNode };

// Module-level constants so React Flow sees identity-stable references
// across renders. New objects per render would force `edges` to look
// "changed" to ReactFlow's reconciler and re-mount the SVG paths.
const EDGE_STYLE = { strokeWidth: 2.5, stroke: "var(--color-brand-500)" };
const EDGE_STYLE_ANIMATED = { strokeWidth: 2.5, stroke: "var(--color-brand-500)" };
const CONNECTION_LINE_STYLE = { strokeWidth: 2.5, stroke: "var(--color-brand-500)" };
const DEFAULT_EDGE_OPTIONS = { type: "default", style: EDGE_STYLE };

/** Stable string hash of every dep relationship in the project. Edges only
 *  need to be rebuilt when this changes — NOT when a card position is
 *  dragged or when a task status flips. Used as the sole dep of the
 *  initialEdges useMemo to break the "drag a card → edges all flicker"
 *  cascade the user reported. */
function computeDepsKey(tasks: Task[]): string {
  const parts: string[] = [];
  for (const t of tasks) {
    parts.push(`${t.id}<${(t.deps ?? []).slice().sort().join(",")}|${t.status}`);
  }
  return parts.sort().join(";");
}

interface CanvasBlueprintProps {
  projectId: string;
  tasks: Task[];
  selectedTaskId: string | null;
  projectRunning: boolean;
  onSelect: (task: Task) => void;
  onAction: (action: TaskAction) => void;
  /** Called when the user clicks empty pane area — drops the task
   *  selection so TaskHeader switches back to project info. */
  onDeselect?: () => void;
}

type PaneMenu = { kind: "pane"; flowX: number; flowY: number; clientX: number; clientY: number };
type NodeMenu = { kind: "node"; task: Task; clientX: number; clientY: number };
type Menu = PaneMenu | NodeMenu | null;

function CanvasBlueprint({
  projectId,
  tasks,
  selectedTaskId,
  projectRunning,
  onSelect,
  onAction,
  onDeselect,
}: CanvasBlueprintProps) {
  const theme = useThemeStore((s) => s.theme);
  const updateTask = useUpdateTask();
  const createTask = useCreateTask();
  const deleteTask = useDeleteTask();
  const [menu, setMenu] = useState<Menu>(null);

  // Compute auto-layout once per task-list change; per-task persisted
  // position overrides it when present.
  const autoLayout = useMemo(() => computeAutoLayout(tasks), [tasks]);
  const indexById = useMemo(() => {
    const m = new Map<string, number>();
    tasks.forEach((t, i) => m.set(t.id, i));
    return m;
  }, [tasks]);

  // Build ReactFlow nodes from tasks. Memoised on tasks + the auxiliary
  // callbacks that the custom node needs.
  const initialNodes: Node[] = useMemo(
    () =>
      tasks.map((t) => {
        const auto = autoLayout.get(t.id) ?? { x: 40, y: 40 };
        const x = t.position_x ?? auto.x;
        const y = t.position_y ?? auto.y;
        return {
          id: t.id,
          type: "task",
          position: { x, y },
          data: {
            task: t,
            index: indexById.get(t.id) ?? 0,
            projectRunning,
            onSelect,
            onAction,
          } satisfies CanvasTaskNodeData,
          selected: t.id === selectedTaskId,
        };
      }),
    [tasks, autoLayout, indexById, projectRunning, onSelect, onAction, selectedTaskId],
  );

  // depsKey changes only when a dep is added/removed/reassigned OR when a
  // task status changes (so `animated` on the inbound edge can flip). It
  // does NOT change when a card position is dragged → initialEdges stays
  // reference-stable across drags → React Flow doesn't re-mount paths.
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;
  const depsKey = useMemo(() => computeDepsKey(tasks), [tasks]);
  const initialEdges: Edge[] = useMemo(
    () => {
      const list = tasksRef.current;
      return list.flatMap((t) =>
        (t.deps ?? []).map<Edge>((depId) => ({
          id: `e_${depId}_${t.id}`,
          source: depId,
          target: t.id,
          // Bezier curve (default) is the closest visual match to the
          // previous SVG layer's `C ... C ...` paths.
          type: "default",
          animated: t.status === "running",
          style: t.status === "running" ? EDGE_STYLE_ANIMATED : EDGE_STYLE,
        })),
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [depsKey],
  );

  const [nodes, setNodes, onNodesChangeBase] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChangeBase] = useEdgesState(initialEdges);

  // ── Stable sync from server → local state ─────────────────────────
  //
  // Original implementation `setNodes(initialNodes)` blew away local
  // node state on every project refetch — including positions the user
  // had just dragged but whose PUT hadn't round-tripped yet, AND fresh
  // node objects every render which made ReactFlow re-issue draws and
  // produced the "lines flicker / jump" symptom.
  //
  // The fix is a merge: keep the existing local node (with its current
  // position) when the task still exists, update only `data` and
  // `selected`; add nodes for new tasks; drop nodes for deleted ones.
  useEffect(() => {
    setNodes((current) => {
      const currentById = new Map(current.map((n) => [n.id, n]));
      const merged: Node[] = [];
      for (const fresh of initialNodes) {
        const existing = currentById.get(fresh.id);
        if (existing) {
          merged.push({
            ...existing,
            data: fresh.data,
            selected: fresh.selected,
          });
        } else {
          // New task — use the server position (or the auto-layout
          // fallback already baked into fresh.position).
          merged.push(fresh);
        }
      }
      return merged;
    });
  }, [initialNodes, setNodes]);

  // Edges are derived from `tasks[].deps` and have stable IDs, so a
  // straight replace is fine; ReactFlow diffs by id and skips re-renders
  // when the edge hasn't changed.
  useEffect(() => setEdges(initialEdges), [initialEdges, setEdges]);

  // Persist position on drag-end. Ignored if project is running (the
  // ReactFlow nodesDraggable prop already prevents drag, but the hook
  // doesn't hurt as a belt-and-suspenders).
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      onNodesChangeBase(changes);
      if (projectRunning) return;
      for (const c of changes) {
        if (c.type === "position" && c.dragging === false && c.position) {
          updateTask.mutate({
            taskId: c.id,
            position_x: c.position.x,
            position_y: c.position.y,
          });
        }
      }
    },
    [onNodesChangeBase, projectRunning, updateTask],
  );

  // Persist edge deletions (Del key on selected edge → onEdgesChange with
  // type=remove). For each removed edge, PUT the target's deps minus source.
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      onEdgesChangeBase(changes);
      if (projectRunning) return;
      for (const c of changes) {
        if (c.type === "remove") {
          // Look up the just-removed edge before state catches up.
          const removed = edges.find((e) => e.id === c.id);
          if (!removed) continue;
          const target = tasks.find((t) => t.id === removed.target);
          if (!target) continue;
          const nextDeps = (target.deps ?? []).filter((d) => d !== removed.source);
          updateTask.mutate({ taskId: target.id, deps: nextDeps });
        }
      }
    },
    [onEdgesChangeBase, projectRunning, edges, tasks, updateTask],
  );

  // Manual connect (drag from source handle to target handle). Validates
  // self-loops + cycles via the shared depCycle helper, then PUTs the new
  // deps list on the target.
  const onConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      if (conn.source === conn.target) return;
      const depMap = buildDepMap(tasks);
      if (wouldCreateCycle(conn.source, conn.target, depMap)) {
        // eslint-disable-next-line no-console
        console.warn("canvas.connect_rejected_cycle", conn);
        return;
      }
      const target = tasks.find((t) => t.id === conn.target);
      if (!target) return;
      if ((target.deps ?? []).includes(conn.source)) return; // already linked
      const nextDeps = [...(target.deps ?? []), conn.source];
      setEdges((eds) => addEdge({ ...conn, id: `e_${conn.source}_${conn.target}` }, eds));
      updateTask.mutate({ taskId: target.id, deps: nextDeps });
    },
    [tasks, setEdges, updateTask],
  );

  const isValidConnection = useCallback(
    (conn: Connection | Edge) => {
      if (!conn.source || !conn.target) return false;
      if (conn.source === conn.target) return false;
      return !wouldCreateCycle(conn.source, conn.target, buildDepMap(tasks));
    },
    [tasks],
  );

  // Right-click on empty pane → "新建任务" menu. Right-click on a node →
  // "编辑 / 删除" menu. Both menus are suppressed while the project is
  // running so the canvas behaves as read-only.
  const handlePaneContextMenu = useCallback(
    (event: React.MouseEvent | MouseEvent) => {
      event.preventDefault();
      if (projectRunning) return;
      const e = event as React.MouseEvent;
      // Convert client coords → flow coords using the pane bounding rect.
      // ReactFlow exposes `screenToFlowPosition` via useReactFlow(), but
      // doing the conversion manually here keeps the component free of
      // the hook ordering / Provider wrapper requirements.
      const pane = (e.currentTarget as HTMLElement | null)?.getBoundingClientRect();
      const flowX = pane ? e.clientX - pane.left : e.clientX;
      const flowY = pane ? e.clientY - pane.top : e.clientY;
      setMenu({ kind: "pane", flowX, flowY, clientX: e.clientX, clientY: e.clientY });
    },
    [projectRunning],
  );

  const handleNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: Node) => {
      event.preventDefault();
      if (projectRunning) return;
      const task = tasks.find((t) => t.id === node.id);
      if (!task) return;
      setMenu({ kind: "node", task, clientX: event.clientX, clientY: event.clientY });
    },
    [projectRunning, tasks],
  );

  const closeMenu = () => setMenu(null);

  // ── Menu actions ──────────────────────────────────────────────
  function handleCreateAt(flowX: number, flowY: number) {
    createTask.mutate({
      project_id: projectId,
      title: "新任务",
      position_x: flowX,
      position_y: flowY,
    });
    closeMenu();
  }

  function handleDeleteTask(taskId: string) {
    if (!confirm("确定删除该任务？下游任务的依赖会自动清理。")) {
      closeMenu();
      return;
    }
    deleteTask.mutate(taskId);
    closeMenu();
  }

  // Empty-state hint (the old <Blueprint/> showed "暂无任务" centered; with
  // the canvas, the user needs to know they can right-click to create one).
  if (tasks.length === 0) {
    return (
      <div
        className="flex h-full flex-col items-center justify-center gap-2 text-sm"
        style={{ color: "var(--color-ink-ghost)" }}
      >
        <span>暂无任务</span>
        <button
          type="button"
          onClick={() =>
            createTask.mutate({
              project_id: projectId,
              title: "新任务",
              position_x: 100,
              position_y: 100,
            })
          }
          className="rounded-lg px-3 py-1.5 text-xs font-medium text-white"
          style={{ backgroundColor: "var(--color-brand-500)" }}
        >
          + 新建任务
        </button>
      </div>
    );
  }

  return (
    <div
      className="relative h-full w-full"
      style={{ backgroundColor: "var(--color-surface)" }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        onPaneContextMenu={handlePaneContextMenu}
        onNodeContextMenu={handleNodeContextMenu}
        onPaneClick={() => {
          closeMenu();
          // Drop the task selection so the top TaskHeader switches its
          // focus back to project-level info.
          onDeselect?.();
        }}
        nodesDraggable={!projectRunning}
        nodesConnectable={!projectRunning}
        elementsSelectable
        colorMode={theme === "dark" ? "dark" : "light"}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
        defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
        connectionLineStyle={CONNECTION_LINE_STYLE}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>

      {/* Floating context menu (single shared overlay; light/dark via Tailwind). */}
      {menu && (
        <div
          className="fixed z-50 min-w-[140px] overflow-hidden rounded-md border border-zinc-200 bg-white text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900"
          style={{ left: menu.clientX, top: menu.clientY }}
          onClick={(e) => e.stopPropagation()}
          role="menu"
        >
          {menu.kind === "pane" && (
            <button
              type="button"
              onClick={() => handleCreateAt(menu.flowX, menu.flowY)}
              className="block w-full px-3 py-2 text-left text-zinc-700 hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
            >
              + 新建任务
            </button>
          )}
          {menu.kind === "node" && (
            <>
              <button
                type="button"
                onClick={() => {
                  onAction({ kind: "edit", task: menu.task });
                  closeMenu();
                }}
                className="block w-full px-3 py-2 text-left text-zinc-700 hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
              >
                编辑
              </button>
              <button
                type="button"
                onClick={() => handleDeleteTask(menu.task.id)}
                className="block w-full px-3 py-2 text-left text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"
              >
                删除
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default CanvasBlueprint;
