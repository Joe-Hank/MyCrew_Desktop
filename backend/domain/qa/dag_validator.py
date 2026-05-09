"""DAG robustness validation: topological sort, reference integrity, connectivity."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DagValidationError:
    kind: str
    message: str
    task_ids: list[str] = field(default_factory=list)


def validate_dag(tasks: list[dict]) -> list[DagValidationError]:
    errors: list[DagValidationError] = []
    task_ids = {t["id"] for t in tasks}
    deps_map: dict[str, list[str]] = {}

    for t in tasks:
        raw_deps = t.get("deps", [])
        if isinstance(raw_deps, str):
            import json
            try:
                raw_deps = json.loads(raw_deps)
            except (json.JSONDecodeError, TypeError):
                raw_deps = []
        deps_map[t["id"]] = list(raw_deps)

    errors.extend(_check_reference_integrity(deps_map, task_ids))
    errors.extend(_check_cycles(deps_map, task_ids))
    errors.extend(_check_connectivity(deps_map, task_ids))
    errors.extend(_check_entry_nodes(deps_map))

    return errors


def _check_reference_integrity(deps_map: dict[str, list[str]],
                                task_ids: set[str]) -> list[DagValidationError]:
    errors = []
    for tid, deps in deps_map.items():
        missing = [d for d in deps if d not in task_ids]
        if missing:
            errors.append(DagValidationError(
                kind="missing_dependency",
                message=f"Task {tid} references non-existent deps: {missing}",
                task_ids=[tid],
            ))
    return errors


def _check_cycles(deps_map: dict[str, list[str]],
                   task_ids: set[str]) -> list[DagValidationError]:
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {tid: WHITE for tid in task_ids}
    cycle_nodes: list[str] = []

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for dep in deps_map.get(node, []):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                cycle_nodes.append(node)
                return True
            if color[dep] == WHITE and dfs(dep):
                cycle_nodes.append(node)
                return True
        color[node] = BLACK
        return False

    for tid in task_ids:
        if color[tid] == WHITE:
            if dfs(tid):
                break

    if cycle_nodes:
        return [DagValidationError(
            kind="cycle_detected",
            message=f"Cycle detected involving tasks: {cycle_nodes}",
            task_ids=cycle_nodes,
        )]
    return []


def _check_connectivity(deps_map: dict[str, list[str]],
                         task_ids: set[str]) -> list[DagValidationError]:
    if len(task_ids) <= 1:
        return []

    adj: dict[str, set[str]] = {tid: set() for tid in task_ids}
    for tid, deps in deps_map.items():
        for d in deps:
            if d in task_ids:
                adj[tid].add(d)
                adj[d].add(tid)

    visited: set[str] = set()
    stack = [next(iter(task_ids))]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adj[node] - visited)

    orphans = task_ids - visited
    if orphans:
        return [DagValidationError(
            kind="disconnected_graph",
            message=f"Orphan tasks not connected to main graph: {sorted(orphans)}",
            task_ids=sorted(orphans),
        )]
    return []


def _check_entry_nodes(deps_map: dict[str, list[str]]) -> list[DagValidationError]:
    entry = [tid for tid, deps in deps_map.items() if not deps]
    if not entry:
        return [DagValidationError(
            kind="no_entry_node",
            message="No entry nodes found (all tasks have dependencies — likely a cycle)",
            task_ids=[],
        )]
    return []
