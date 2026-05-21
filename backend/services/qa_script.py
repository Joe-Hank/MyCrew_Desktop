"""Script-based Crew QA (Stage 1).

Deterministic Python replacement for the LLM QA step. Returns the same
shape as the current `emit_output` payload — `{verdict, file_paths,
issues, summary}` — so call sites can swap LLM QA → script QA via
feature flag without changing downstream wiring (`_save_task_output`,
`_collect_verdict_errors`, failure_analyzer, IO viewer).

Stage 1 deliverables (this file):
  - `verify_task_qa(task_id, captured_results)` — top-level entry
  - per-suffix check functions (image / audio / 3D / Unity serialized)
  - Executor verdict propagation
  - dedup against the existing `_dedup_errors` utility in workflow_svc

NOT in Stage 1:
  - Crew agent_sequence step.kind="script_qa" dispatch (Stage 2)
  - Wiring into workflow_svc._run_crew (Stage 2)
  - UI badge to mark step as auto-verified (Stage 2)

Design notes:
  - Check functions are sync, pure (filesystem read only), and return
    `list[str]` of issue strings. No raising — a check that crashes
    internally swallows + reports the crash as an issue.
  - Magic-bytes checks for image/audio/code are *omitted* — they're
    subsumed by the deeper validators (Pillow / wave / tree-sitter all
    fail on bad headers anyway). Only retained for 3D models where we
    have no deeper validator.
  - .meta sibling check is intentionally *not* performed (see the
    user-facing discussion of why — Unity creates them on Refresh, and
    racing the Editor produces flaky false-positives).
"""
from __future__ import annotations

import json
import re
import struct
import wave
from pathlib import Path
from typing import Any

import structlog

from infra.repo import crud

log = structlog.get_logger()


_PASS_TOKENS = {"pass", "passed", "success", "ok", "true"}


# ── Suffix dispatch table ──────────────────────────────────────────

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg"}
_UNITY_SERIALIZED_SUFFIXES = {".prefab", ".unity", ".asset", ".mat", ".controller", ".anim"}
_MODEL_3D_SUFFIXES = {".fbx", ".blend", ".obj"}


# ── Top-level entry ────────────────────────────────────────────────

async def verify_task_qa(
    task_id: str,
    captured_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run all QA checks for a task and return the verdict payload.

    `captured_results` is the list of per-child captured payloads from a
    fan-out Executor step (or the singleton payload from a sequential
    Executor). When empty/None, the only signals available are
    file-on-disk + contract.
    """
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        return _verdict_fail(
            paths=[], issues=[f"task {task_id} not found"],
            summary="QA aborted — task row gone",
        )

    project = await crud.get_by_id("projects", task["project_id"])
    if not project:
        return _verdict_fail(
            paths=[], issues=[f"project {task['project_id']} not found"],
            summary="QA aborted — project row gone",
        )

    root_str = project.get("root_path") or ""
    root = Path(root_str) if root_str else None

    output_paths = _parse_json_list(task.get("output_paths"))
    output_schema = _parse_json_dict(task.get("output_schema"))
    detail = task.get("detail") or ""
    code_contract = _parse_json_dict(task.get("code_contract"))

    issues: list[str] = []

    # 1. Upstream Executor verdict propagation.
    issues.extend(_collect_upstream_failures(captured_results or []))

    # 2. Per-path structural verification.
    if root is None:
        if output_paths:
            issues.append("project root_path 未配置，无法定位产出文件")
    else:
        for rel_path in output_paths:
            abs_path = (root / rel_path).resolve()
            # Path-escape guard: refuse to look at anything that climbs
            # out of root_path via .. or absolute-path shenanigans.
            try:
                abs_path.relative_to(root.resolve())
            except ValueError:
                issues.append(f"{rel_path}: 路径越过项目根目录，拒绝检查")
                continue
            issues.extend(_check_path(abs_path, rel_path, output_schema, detail))

    # 3. Code contract — delegate to the existing AST verifier so we
    # keep a single source of truth. _verify_code_contract takes
    # (project_id, task_id) and returns list[str]; no-op when the task
    # has no contract bound.
    if code_contract and output_paths:
        try:
            from services.workflow_svc import workflow_svc
            contract_errors = await workflow_svc._verify_code_contract(
                project["id"], task_id,
            )
            issues.extend(contract_errors)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "qa_script.contract_verify_failed",
                task_id=task_id, error=str(exc),
            )
            issues.append(f"代码契约校验异常：{exc}")

    # 4. Dedup before return — same rules workflow_svc applies later.
    try:
        from services.workflow_svc import _dedup_errors
        issues = _dedup_errors(issues)
    except ImportError:
        pass  # never trip in production, only when the module is mocked

    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "file_paths": output_paths,
        "issues": issues,
        "summary": _build_summary(verdict, output_paths, issues),
    }


# ── Path dispatch ──────────────────────────────────────────────────

def _check_path(
    abs_path: Path, rel_path: str, schema: dict, detail: str,
) -> list[str]:
    """Top-level per-file check. Bottoms out at suffix-keyed dispatch."""
    if not abs_path.exists():
        return [f"{rel_path}: 文件不存在"]
    if not abs_path.is_file():
        return [f"{rel_path}: 不是文件（可能是目录）"]
    try:
        size = abs_path.stat().st_size
    except OSError as exc:
        return [f"{rel_path}: 读取文件失败 ({exc})"]
    if size == 0:
        return [f"{rel_path}: 文件为空 (0 bytes)"]

    suffix = abs_path.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return _check_image(abs_path, rel_path, schema, detail)
    if suffix in _AUDIO_SUFFIXES:
        return _check_audio(abs_path, rel_path)
    if suffix == ".cs":
        # Code contract step handles signature checks; here we only
        # confirm size > 0 + utf-8 readability (placeholder garbage
        # would fail this).
        return _check_csharp_text(abs_path, rel_path)
    if suffix in _UNITY_SERIALIZED_SUFFIXES:
        return _check_unity_serialized(abs_path, rel_path)
    if suffix in _MODEL_3D_SUFFIXES:
        return _check_3d_model(abs_path, rel_path, size)
    # Unknown extension: existence + non-empty is all we can promise.
    return []


# ── Image checks ───────────────────────────────────────────────────

_TRANSPARENT_KEYWORDS = (
    "透明", "alpha", "transparent", "无背景", "去背景", "no background",
)


def _check_image(
    abs_path: Path, rel_path: str, schema: dict, detail: str,
) -> list[str]:
    """Validate PNG/JPG via Pillow:
      - file parses as image (subsumes magic-byte check)
      - dimensions match output_schema width/height const, if set
      - alpha channel present when task.detail asks for transparent bg
        (reported as `[warning]` so the verdict stays pass)
    """
    issues: list[str] = []
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return [f"{rel_path}: Pillow 未安装，无法校验图片"]

    try:
        with Image.open(abs_path) as img:
            img.load()  # force decode; lazy open hides truncation
            actual_w, actual_h = img.size
            mode = img.mode
    except UnidentifiedImageError:
        return [f"{rel_path}: 不是合法的图片文件（魔数/编码错误）"]
    except Exception as exc:  # noqa: BLE001
        return [f"{rel_path}: 图片解码失败 ({exc})"]

    exp_w, exp_h = _extract_image_dims(schema)
    if exp_w is not None and actual_w != exp_w:
        issues.append(
            f"{rel_path}: 宽度不匹配 actual={actual_w} 期望={exp_w}"
        )
    if exp_h is not None and actual_h != exp_h:
        issues.append(
            f"{rel_path}: 高度不匹配 actual={actual_h} 期望={exp_h}"
        )

    if _detail_requests_transparency(detail):
        warn = _check_alpha(abs_path, rel_path, mode)
        if warn:
            issues.append(warn)

    return issues


def _extract_image_dims(schema: dict) -> tuple[int | None, int | None]:
    """Pull (width, height) out of a PM output_schema. Supports three
    increasingly forgiving shapes:
      - `properties.width.const = 64` (PM v5 preferred — strict)
      - `properties.width.examples = [64]` (PM v4 fallback)
      - `properties.width.description = '像素宽，64'` — regex rescue
        when PM Phase 5 LLM pins the dim in prose instead of const.
    Returns (None, None) when the schema doesn't constrain dimensions.
    """
    import re
    if not isinstance(schema, dict):
        return None, None
    props = schema.get("properties")
    if not isinstance(props, dict):
        return None, None

    def _read(key: str) -> int | None:
        spec = props.get(key)
        if not isinstance(spec, dict):
            return None
        if isinstance(spec.get("const"), int):
            return spec["const"]
        ex = spec.get("examples")
        if isinstance(ex, list) and ex and isinstance(ex[0], int):
            return ex[0]
        # Description fallback: regex first plausible integer.
        desc = spec.get("description")
        if isinstance(desc, str):
            for match in re.finditer(r"(\d{2,5})", desc):
                n = int(match.group(1))
                if 8 <= n <= 8192:
                    return n
        return None

    return _read("width"), _read("height")


def _detail_requests_transparency(detail: str) -> bool:
    if not isinstance(detail, str):
        return False
    low = detail.lower()
    return any(k in low for k in _TRANSPARENT_KEYWORDS)


def _check_alpha(abs_path: Path, rel_path: str, mode: str) -> str | None:
    """Return a warning string if the image lacks transparency despite
    being requested. Warning, not error — alpha mis-flagging is the
    most error-prone check, see the design note.
    """
    if mode not in ("RGBA", "LA", "PA"):
        return (
            f"{rel_path}: [warning] 任务要求透明背景但图片 mode={mode} "
            f"（非 RGBA/LA/PA，无 alpha 通道）"
        )
    try:
        from PIL import Image
        with Image.open(abs_path) as img:
            alpha = img.getchannel("A")
            extrema = alpha.getextrema()  # (min, max)
            if extrema[0] >= 255:
                return (
                    f"{rel_path}: [warning] 任务要求透明背景但所有像素 alpha=255 "
                    f"（实际是不透明图）"
                )
    except Exception as exc:  # noqa: BLE001
        return f"{rel_path}: [warning] 透明度检查失败 ({exc})"
    return None


# ── Audio checks ───────────────────────────────────────────────────

def _check_audio(abs_path: Path, rel_path: str) -> list[str]:
    """Validate WAV via stdlib `wave`. MP3/OGG fall through to magic
    bytes only — we don't ship an mp3 decoder in core deps.
    """
    suffix = abs_path.suffix.lower()
    if suffix == ".wav":
        return _check_wav(abs_path, rel_path)
    if suffix == ".mp3":
        return _check_mp3_magic(abs_path, rel_path)
    if suffix == ".ogg":
        return _check_ogg_magic(abs_path, rel_path)
    return []


def _check_wav(abs_path: Path, rel_path: str) -> list[str]:
    try:
        with wave.open(str(abs_path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
    except wave.Error as exc:
        return [f"{rel_path}: 不是合法的 WAV 文件 ({exc})"]
    except Exception as exc:  # noqa: BLE001
        return [f"{rel_path}: WAV 解析异常 ({exc})"]
    if frames == 0:
        return [f"{rel_path}: WAV 文件 frames=0 (空音频)"]
    duration = frames / rate if rate else 0
    if duration < 0.05:  # 50ms — anything below is almost certainly a stub
        return [f"{rel_path}: WAV 时长过短 ({duration:.3f}s)，疑似占位文件"]
    return []


def _check_mp3_magic(abs_path: Path, rel_path: str) -> list[str]:
    head = _read_head(abs_path, 3)
    if head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return []
    return [f"{rel_path}: 不是合法的 MP3 (magic bytes 不符)"]


def _check_ogg_magic(abs_path: Path, rel_path: str) -> list[str]:
    head = _read_head(abs_path, 4)
    if head == b"OggS":
        return []
    return [f"{rel_path}: 不是合法的 Ogg (magic bytes 不符)"]


# ── C# checks ──────────────────────────────────────────────────────

def _check_csharp_text(abs_path: Path, rel_path: str) -> list[str]:
    """Cheap pre-check before tree-sitter / contract: must be UTF-8
    decodable + non-trivial length + contain at least one C#-shaped
    token (`class`, `enum`, `struct`, `interface`, `namespace`, `using`).
    Stops `write_file('foo.cs', 'TODO')` placeholders from sailing past
    the contract step's signature scan (which would catch them too, but
    with a less obvious error message).
    """
    try:
        text = abs_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"{rel_path}: .cs 文件 UTF-8 解码失败（非文本占位）"]
    except OSError as exc:
        return [f"{rel_path}: .cs 文件读取失败 ({exc})"]
    if len(text) < 20:
        return [f"{rel_path}: .cs 文件长度过短 ({len(text)} 字符)，疑似占位"]
    if not re.search(r"\b(class|enum|struct|interface|namespace|using)\b", text):
        return [f"{rel_path}: .cs 文件不含任何 C# 顶层关键字（class/enum/struct/...）"]
    return []


# ── Unity serialized YAML checks ───────────────────────────────────

# Unity .prefab / .unity / .asset start with this exact preamble — we
# don't parse the YAML proper because PyYAML doesn't understand Unity's
# `!u!` tag URI and would false-positive on legitimate files.
_UNITY_YAML_HEAD_RE = re.compile(
    rb"^%YAML\s+1\.1\s*\n%TAG\s+!u!\s+tag:unity3d\.com,2011:\s*\n--- !u!\d+\s+&\d+",
)


def _check_unity_serialized(abs_path: Path, rel_path: str) -> list[str]:
    """Validate Unity YAML preamble. Cheap, ~6 lines of regex work, no
    PyYAML — see the design note for why."""
    suffix = abs_path.suffix.lower()
    head = _read_head(abs_path, 512)
    # .mat / .controller / .anim / .asset use the same preamble as
    # .prefab / .unity, so one regex covers them all.
    if not _UNITY_YAML_HEAD_RE.search(head):
        return [
            f"{rel_path}: 不是合法的 Unity {suffix} 序列化文件 "
            f"(缺少 %YAML 1.1 / %TAG !u! 头)"
        ]
    return []


# ── 3D model checks ────────────────────────────────────────────────

def _check_3d_model(abs_path: Path, rel_path: str, size: int) -> list[str]:
    """Magic-bytes + minimum-size sanity. We don't have a tree-sitter
    equivalent for these formats.

    Min size threshold (200B) — empirically below this is always a stub.
    Real FBX files are kilobytes minimum.
    """
    if size < 200:
        return [f"{rel_path}: 文件过小 ({size} bytes)，疑似占位"]
    suffix = abs_path.suffix.lower()
    head = _read_head(abs_path, 32)
    if suffix == ".fbx":
        # ASCII: starts with "; FBX " ; Binary: "Kaydara FBX Binary\x20\x20\x00".
        if head.startswith(b"; FBX") or head.startswith(b"Kaydara FBX Binary"):
            return []
        return [f"{rel_path}: 不是合法的 FBX (magic bytes 不符)"]
    if suffix == ".blend":
        # "BLENDER" + version chars
        if head.startswith(b"BLENDER"):
            return []
        return [f"{rel_path}: 不是合法的 .blend (magic bytes 不符)"]
    if suffix == ".obj":
        # OBJ is plain text; check first line decodes + contains 'v ' / 'f '
        try:
            text = abs_path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            return [f"{rel_path}: .obj 文件 UTF-8 解码失败"]
        if not re.search(r"^[vf]\s", text[:4096], re.MULTILINE):
            return [
                f"{rel_path}: .obj 文件首 4KB 中无 vertex/face 行 (`v ` / `f `)"
            ]
    return []


# ── Helpers ────────────────────────────────────────────────────────

def _collect_upstream_failures(results: list[dict]) -> list[str]:
    """Propagate any Executor-self-reported failure into our issues
    list. Mirrors `_collect_verdict_errors` semantics but operates on
    the list-of-payloads shape used by fan-out aggregates.
    """
    out: list[str] = []
    for i, r in enumerate(results):
        if not isinstance(r, dict):
            continue
        v = r.get("verdict")
        if v is None:
            continue
        verdict_str = str(v).strip().lower()
        if not verdict_str or verdict_str in _PASS_TOKENS:
            continue
        out.append(
            f"上游 Executor 第 {i + 1} 项 verdict='{v}'"
        )
        for iss in (r.get("issues") or [])[:5]:
            if isinstance(iss, str) and iss.strip():
                out.append(f"  · {iss.strip()[:200]}")
    return out


def _read_head(abs_path: Path, n: int) -> bytes:
    try:
        with abs_path.open("rb") as f:
            return f.read(n)
    except OSError:
        return b""


def _parse_json_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, str)]
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, str)]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _parse_json_dict(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _verdict_fail(*, paths: list[str], issues: list[str], summary: str) -> dict:
    return {
        "verdict": "fail",
        "file_paths": paths,
        "issues": issues,
        "summary": summary,
    }


def _build_summary(verdict: str, paths: list[str], issues: list[str]) -> str:
    """Compact human-readable summary line. Replaces the LLM's free-
    form summary string. Stable phrasing so failure_analyzer can rely
    on it.
    """
    n = len(paths)
    if verdict == "pass":
        return f"自动验收通过：{n} 个产物全部满足契约。"
    # On failure, surface counts of {error, warning} so the user knows
    # how serious the issue list is at a glance.
    n_warn = sum(1 for s in issues if "[warning]" in s)
    n_err = len(issues) - n_warn
    return (
        f"自动验收失败：{n} 个产物，{n_err} 项错误"
        + (f" + {n_warn} 项警告" if n_warn else "")
        + "（脚本验收，未调用 LLM）。"
    )


# Compiled struct unused; kept for symmetry with potential future
# binary-format checks. Suppress lint by referencing.
_ = struct  # noqa
