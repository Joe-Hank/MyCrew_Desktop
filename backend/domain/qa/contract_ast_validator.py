"""AST-based code contract validator (v2 — replaces regex substring match).

Uses tree-sitter-c-sharp to parse both contract signatures and generated
.cs files into structured member declarations, then matches by
**semantic key** (kind + name) and verifies type / param / accessor
shape. Body style (auto-property vs full property vs expression-bodied)
is irrelevant — only the declaration surface matters.

Why this exists: the old `contract_validator.normalize_csharp +
substring match` was too strict on property body. Production case
(2026-05-18, proj_633b6172d873 GameManager.cs): contract had
`public int Score { get; set; }`, LLM wrote full-property with
event-firing setter (`{ get => _x; set { OnX?.Invoke(); } }`). Both
are valid C# and the public API is the same, but the literal substring
`{ get; set; }` doesn't appear in the second form → false negative.

Public entry: `verify_contract(contract, project_root) -> list[str]`
mirrors the legacy validator's signature so workflow_svc can drop-in.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


# Lazy parser init — tree-sitter binding allocates a native module
# handle the first time. Module-level singleton is fine, parsers are
# reusable across calls.
_PARSER = None


def _get_parser():
    global _PARSER
    if _PARSER is None:
        import tree_sitter_c_sharp as tscs
        from tree_sitter import Language, Parser
        _PARSER = Parser(Language(tscs.language()))
    return _PARSER


# ── AST helpers ─────────────────────────────────────────────────────


def _node_text(src: bytes, node) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


def _modifiers(src: bytes, decl_node) -> list[str]:
    """List of modifier strings (public/private/static/etc.) before the
    decl keyword."""
    out: list[str] = []
    for c in decl_node.children:
        if c.type == "modifier":
            out.append(_node_text(src, c))
    return out


def _field_text(src: bytes, parent, field_name: str) -> str | None:
    c = parent.child_by_field_name(field_name)
    return _node_text(src, c) if c is not None else None


def _accessor_names(src: bytes, prop_node) -> list[str]:
    """Return the list of accessor keywords on a property
    (typically ['get'], ['get', 'set'], or ['get', 'init'])."""
    accs: list[str] = []
    al = prop_node.child_by_field_name("accessors")
    if al is None:
        # Expression-bodied property `=> _x;` has no accessor_list; it's
        # effectively get-only.
        if any(c.type == "=>" for c in prop_node.children):
            return ["get"]
        return accs
    for c in al.children:
        if c.type == "accessor_declaration":
            name = c.child_by_field_name("name")
            if name is not None:
                accs.append(_node_text(src, name))
    return accs


def _params(src: bytes, method_node) -> list[tuple[str, str]]:
    """Return [(type_str, name_str), ...] for a method's parameters."""
    plist = method_node.child_by_field_name("parameters")
    if plist is None:
        return []
    out: list[tuple[str, str]] = []
    for c in plist.children:
        if c.type == "parameter":
            t = _field_text(src, c, "type") or ""
            n = _field_text(src, c, "name") or ""
            out.append((t, n))
    return out


def _base_types(src: bytes, class_node) -> list[str]:
    """For `public class Foo : A, B` returns ['A', 'B']."""
    out: list[str] = []
    for c in class_node.children:
        if c.type == "base_list":
            for bc in c.children:
                if bc.type in ("identifier", "generic_name", "qualified_name"):
                    out.append(_node_text(src, bc))
    return out


def _event_field_names(src: bytes, ev_node) -> list[tuple[str, str]]:
    """`public event Action OnA, OnB;` → [('Action', 'OnA'), ('Action', 'OnB')].

    The event_field_declaration wraps a variable_declaration; iterate its
    declarators."""
    # event_field has children: modifier* "event" variable_declaration ";"
    out: list[tuple[str, str]] = []
    for c in ev_node.children:
        if c.type == "variable_declaration":
            ev_type = _field_text(src, c, "type") or ""
            for vc in c.children:
                if vc.type == "variable_declarator":
                    name = _field_text(src, vc, "name") or _node_text(src, vc)
                    out.append((ev_type, name))
    return out


# ── Member extraction ──────────────────────────────────────────────


def _extract_members(src: bytes) -> list[dict]:
    """Walk the parse tree and emit a flat list of member dicts.

    Recurses into namespace + class so nested members surface at the
    top level (useful since contracts don't model namespace boundaries).
    """
    parser = _get_parser()
    tree = parser.parse(src)
    members: list[dict] = []

    def visit(node) -> None:
        t = node.type
        if t == "class_declaration":
            members.append({
                "kind": "class",
                "name": _field_text(src, node, "name") or "",
                "modifiers": _modifiers(src, node),
                "base_types": _base_types(src, node),
            })
        elif t == "interface_declaration":
            members.append({
                "kind": "interface",
                "name": _field_text(src, node, "name") or "",
                "modifiers": _modifiers(src, node),
            })
        elif t == "struct_declaration":
            members.append({
                "kind": "struct",
                "name": _field_text(src, node, "name") or "",
                "modifiers": _modifiers(src, node),
            })
        elif t == "enum_declaration":
            members.append({
                "kind": "enum",
                "name": _field_text(src, node, "name") or "",
                "modifiers": _modifiers(src, node),
            })
        elif t == "property_declaration":
            members.append({
                "kind": "property",
                "name": _field_text(src, node, "name") or "",
                "type": _field_text(src, node, "type") or "",
                "modifiers": _modifiers(src, node),
                "accessors": _accessor_names(src, node),
            })
        elif t == "method_declaration":
            members.append({
                "kind": "method",
                "name": _field_text(src, node, "name") or "",
                "return_type": _field_text(src, node, "returns") or "",
                "modifiers": _modifiers(src, node),
                "params": _params(src, node),
            })
        elif t == "event_field_declaration":
            for ev_type, ev_name in _event_field_names(src, node):
                members.append({
                    "kind": "event",
                    "name": ev_name,
                    "type": ev_type,
                    "modifiers": _modifiers(src, node),
                })
        elif t == "event_declaration":
            # `public event Action OnX { add { } remove { } }` form.
            members.append({
                "kind": "event",
                "name": _field_text(src, node, "name") or "",
                "type": _field_text(src, node, "type") or "",
                "modifiers": _modifiers(src, node),
            })
        elif t == "field_declaration":
            # field is intentionally a DIFFERENT kind — a contract that
            # demands a property is NOT satisfied by a field, and we
            # want the mismatch flagged.
            for c in node.children:
                if c.type == "variable_declaration":
                    ftype = _field_text(src, c, "type") or ""
                    for vc in c.children:
                        if vc.type == "variable_declarator":
                            fname = _field_text(src, vc, "name") or _node_text(src, vc)
                            members.append({
                                "kind": "field",
                                "name": fname,
                                "type": ftype,
                                "modifiers": _modifiers(src, node),
                            })
        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return members


# ── Contract signature → member dict ────────────────────────────────


def _parse_contract_signature(sig: str, kind: str) -> dict | None:
    """Parse a contract's literal signature into the same dict shape
    as _extract_members.

    Strategy: wrap the signature in a minimal `class _D { <sig>; }`
    so tree-sitter parses it as a class member, then walk the result.
    Some kinds (class, interface) are top-level, not nested — handle
    those without wrapping.
    """
    sig = sig.strip().rstrip(";").rstrip()
    parser = _get_parser()

    if kind in ("class", "interface", "struct", "enum"):
        wrapped = f"{sig} {{}}"
        tree = parser.parse(wrapped.encode("utf-8"))
        for member in _extract_members(wrapped.encode("utf-8")):
            if member["kind"] == kind:
                return member
        return None

    # Property / method / event: must be inside a class for tree-sitter
    # to parse as a member declaration.
    body = "{}"
    if kind == "method":
        body = "{}"
    elif kind == "property":
        if "{" not in sig:
            # Auto-property with no body in contract — synthesize `{ get; }`
            sig_with_body = sig + " { get; }"
        else:
            sig_with_body = sig
        wrapped = f"class _D {{ {sig_with_body} }}"
        members = _extract_members(wrapped.encode("utf-8"))
        for m in members:
            if m["kind"] == "property":
                return m
        return None
    elif kind == "event":
        wrapped = f"class _D {{ {sig}; }}"
        members = _extract_members(wrapped.encode("utf-8"))
        for m in members:
            if m["kind"] == "event":
                return m
        return None
    elif kind == "field":
        # `public int RageLevel` — a bare field decl needs the trailing
        # `;` to parse as field_declaration; without it tree-sitter sees
        # the next `{` and decides it's a property with an empty
        # accessor list (kind='property') → contract lookup misses.
        # 2026-05-19 fix: PlayerController contract had `public int
        # RageLevel` as kind=field which previously returned None →
        # "契约 signature 无法解析" → Debugger skipped it.
        wrapped = f"class _D {{ {sig}; }}"
        members = _extract_members(wrapped.encode("utf-8"))
        for m in members:
            if m["kind"] == "field":
                return m
        return None

    # method / fallback
    wrapped = f"class _D {{ {sig} {body} }}"
    members = _extract_members(wrapped.encode("utf-8"))
    for m in members:
        if m["kind"] == kind:
            return m
    return None


# ── Comparison ──────────────────────────────────────────────────────


def _types_equivalent(a: str, b: str) -> bool:
    """Loose type compare: strip spaces, then literal equal."""
    norm = lambda s: "".join((s or "").split())
    return norm(a) == norm(b)


def _diff_member(expected: dict, actual: dict) -> list[str]:
    """Return list of mismatch strings (empty = full match).

    The (kind, name) is presumed matched by the caller. This function
    checks the secondary shape: type / params / required accessors.
    """
    issues: list[str] = []

    # All kinds: check that contract's modifiers (especially `public`)
    # are present in actual.
    exp_mods = set(expected.get("modifiers") or [])
    act_mods = set(actual.get("modifiers") or [])
    missing_mods = exp_mods - act_mods
    if missing_mods:
        issues.append(f"缺修饰符 {sorted(missing_mods)}")

    if expected["kind"] == "property":
        if not _types_equivalent(expected.get("type") or "", actual.get("type") or ""):
            issues.append(
                f"类型不符 ({expected.get('type')} vs {actual.get('type')})"
            )
        exp_accs = set(expected.get("accessors") or [])
        act_accs = set(actual.get("accessors") or [])
        missing_accs = exp_accs - act_accs
        if missing_accs:
            issues.append(f"缺访问器 {sorted(missing_accs)}")

    elif expected["kind"] == "method":
        if not _types_equivalent(expected.get("return_type") or "",
                                 actual.get("return_type") or ""):
            issues.append(
                f"返回类型不符 ({expected.get('return_type')} vs "
                f"{actual.get('return_type')})"
            )
        exp_p = [p[0] for p in expected.get("params") or []]
        act_p = [p[0] for p in actual.get("params") or []]
        # Compare type sequence only (names ignored)
        norm = lambda s: "".join((s or "").split())
        if [norm(t) for t in exp_p] != [norm(t) for t in act_p]:
            issues.append(f"参数列表不符 ({exp_p} vs {act_p})")

    elif expected["kind"] == "event":
        if not _types_equivalent(expected.get("type") or "", actual.get("type") or ""):
            issues.append(
                f"事件类型不符 ({expected.get('type')} vs {actual.get('type')})"
            )

    elif expected["kind"] == "class":
        # Names match (caller verified); optionally check base_types overlap.
        exp_bases = set(expected.get("base_types") or [])
        act_bases = set(actual.get("base_types") or [])
        missing_bases = exp_bases - act_bases
        if missing_bases and exp_bases:
            issues.append(f"缺 base 类型 {sorted(missing_bases)}")

    return issues


def _find_match(
    actuals: list[dict], expected: dict,
) -> tuple[dict | None, list[dict]]:
    """Find an actual member matching expected by (kind, name).

    Returns (best_match, candidates_with_same_name_but_different_kind).
    The second list lets the caller report "you have a field named X
    but I asked for a property" instead of just "X missing".
    """
    same_name_diff_kind: list[dict] = []
    for a in actuals:
        if a.get("name") != expected.get("name"):
            continue
        if a.get("kind") == expected.get("kind"):
            return a, []
        same_name_diff_kind.append(a)
    return None, same_name_diff_kind


# ── Public entry ────────────────────────────────────────────────────


def verify_contract(contract: dict, project_root: Path) -> list[str]:
    """Walk every contract.files[*].exports[*] and confirm the listed
    declaration appears (AST-level) in the corresponding .cs file.
    Returns a flat list of human-readable error strings; empty = full
    contract honoured. Never raises — unexpected parser errors are
    logged and that file's contract is reported as 'unverifiable'.
    """
    errors: list[str] = []
    for f in contract.get("files") or []:
        path_str = f.get("path") or ""
        if not path_str:
            errors.append("contract.files[].path 为空")
            continue
        abs_path = (
            Path(path_str) if Path(path_str).is_absolute()
            else project_root / path_str
        )
        if not abs_path.exists():
            errors.append(
                f"{path_str}: 文件不存在 — Crew Executor 没产出该 .cs"
            )
            continue
        try:
            src = abs_path.read_bytes()
        except OSError as exc:
            errors.append(f"{path_str}: 读取失败 ({exc})")
            continue

        try:
            actual_members = _extract_members(src)
        except Exception as exc:  # noqa: BLE001
            log.warning("contract_ast.parse_failed",
                        path=path_str, error=str(exc))
            errors.append(f"{path_str}: 解析失败 ({exc})")
            continue

        file_errors: list[str] = []
        for exp_raw in f.get("exports") or []:
            sig = (exp_raw.get("signature") or "").strip()
            kind = exp_raw.get("kind") or ""
            if not sig or not kind:
                continue
            expected = _parse_contract_signature(sig, kind)
            if expected is None:
                file_errors.append(
                    f"契约 signature 无法解析: ({kind}) `{sig}`"
                )
                continue
            actual, same_name = _find_match(actual_members, expected)
            if actual is None:
                if same_name:
                    other_kinds = ", ".join(s["kind"] for s in same_name)
                    file_errors.append(
                        f"({kind}) `{sig}` — 找到同名声明但 kind 不符 "
                        f"(实际是 {other_kinds})"
                    )
                else:
                    file_errors.append(f"({kind}) `{sig}` — 未声明")
                continue
            diff = _diff_member(expected, actual)
            if diff:
                file_errors.append(
                    f"({kind}) `{sig}` — " + "; ".join(diff)
                )

        if file_errors:
            joined = "; ".join(file_errors[:6])
            more = (
                f"（还有 {len(file_errors) - 6} 项）"
                if len(file_errors) > 6 else ""
            )
            errors.append(f"{path_str}: 缺少契约签名 — {joined}{more}")

    if errors:
        log.info("contract_ast.failed", error_count=len(errors))
    return errors


__all__ = ["verify_contract"]
