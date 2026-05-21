"""Deterministic ComfyUI image generation — replaces the LLM-driven
ComfyUI Image Generator step.

Stage 3 of the LLM → Python migration (after Phase 6 rule-assignment
and Stage 2 script QA). The Generator step has zero creative choices
to make: Head's emit_output already pins {width, height, positive_prompt,
negative_prompt, seed} per target path. The remaining work — build the
ComfyUI workflow JSON, POST /prompt, poll /history, fetch the PNG,
resize to target — is purely mechanical and was the most failure-prone
LLM step in the chain (the agent kept dumping ReAct text instead of
calling comfy_*).

This module talks to ComfyUI's HTTP API directly (default 127.0.0.1:8000
per the user's installed desktop app) so it does NOT depend on the
artokun/comfyui-mcp server being up. Bypassing MCP also removes the
serialization layer that was previously masking real errors.

Public entry:
    `generate_image_for_child(child_task_row, head_spec, project_root)`
    Returns an emit_output-shaped dict
    `{verdict, file_paths, width, height, issues, summary}`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()


# ── Config ─────────────────────────────────────────────────────────

DEFAULT_BASE_URL = os.environ.get(
    "MYCREW_COMFYUI_URL",
    "http://127.0.0.1:8000",
)
# Default node parameters. These are the LAST line of defence — Head
# is expected to pin checkpoint + sampler + steps + cfg as part of its
# emit_output payload, since those are creative choices (model = overall
# aesthetic; sampler/steps/cfg = quality vs speed tradeoff). Falling
# back to these defaults is fine for "Head left it blank" but the user
# should consider it a sign that the Art Director step didn't do its
# job.
# Default checkpoint. Moved from majicmixRealistic_v7 (2026-05-20) which
# was forcing every output into photoreal portrait territory regardless
# of project art direction. `cyberpunk.safetensors` is a more neutral SD
# 1.5 fine-tune that takes prompt style cues better. Best long-term:
# user installs `v1-5-pruned-emaonly.safetensors` as the true SD 1.5
# base — see plan file (cuddly-percolating-tome.md) → 风险 + 限制.
DEFAULT_CHECKPOINT = os.environ.get(
    "MYCREW_COMFYUI_CHECKPOINT",
    "cyberpunk.safetensors",
)
DEFAULT_NODE_PARAMS: dict = {
    "steps": 20,
    "cfg": 6.5,
    "sampler": "euler",
    "scheduler": "normal",
    "denoise": 1.0,
}
# SD 1.5 sweet-spot range. Anything below 512 produces noise; above 1024
# is shaky without hi-res fix. We always generate inside this band and
# resize down/up to the contract dim afterwards via PIL.
GEN_MIN, GEN_MAX = 512, 1024
# How long to wait for ComfyUI to finish one image before giving up.
GEN_TIMEOUT_SEC = 180
POLL_INTERVAL_SEC = 2.0


# ── ComfyUI HTTP client ────────────────────────────────────────────


class ComfyHttpError(RuntimeError):
    """Raised when ComfyUI returns an unrecoverable error during
    workflow submission, polling, or output fetch."""


async def _http_get(client: httpx.AsyncClient, path: str, **kw) -> httpx.Response:
    resp = await client.get(path, **kw)
    if resp.status_code >= 400:
        raise ComfyHttpError(
            f"ComfyUI GET {path} → {resp.status_code}: {resp.text[:200]}"
        )
    return resp


async def _http_post(client: httpx.AsyncClient, path: str, json_body: dict) -> httpx.Response:
    resp = await client.post(path, json=json_body)
    if resp.status_code >= 400:
        raise ComfyHttpError(
            f"ComfyUI POST {path} → {resp.status_code}: {resp.text[:200]}"
        )
    return resp


async def _resolve_checkpoint(
    client: httpx.AsyncClient,
    *,
    preferred: str | None = None,
) -> tuple[str, str | None]:
    """Pick a checkpoint that's actually installed. `preferred` is what
    Head asked for (per-path or project-wide). Returns
    `(picked, fallback_warning)` — `fallback_warning` is non-None when
    the preferred wasn't available and we had to substitute.

    Order: preferred → DEFAULT_CHECKPOINT → first installed.
    """
    resp = await _http_get(client, "/object_info/CheckpointLoaderSimple")
    info = resp.json().get("CheckpointLoaderSimple", {})
    options = (
        info.get("input", {}).get("required", {}).get("ckpt_name") or [[]]
    )[0]
    if not isinstance(options, list) or not options:
        raise ComfyHttpError("ComfyUI has no checkpoints installed")

    if preferred and preferred in options:
        return preferred, None
    if preferred:
        log.warning(
            "image_gen.checkpoint_preferred_unavailable",
            preferred=preferred, available=options[:5],
        )
        warning = (
            f"Head 指定的 checkpoint='{preferred}' 未安装，"
            f"实际使用 '{DEFAULT_CHECKPOINT if DEFAULT_CHECKPOINT in options else options[0]}'"
        )
    else:
        warning = None

    if DEFAULT_CHECKPOINT in options:
        return DEFAULT_CHECKPOINT, warning
    log.warning(
        "image_gen.checkpoint_fallback",
        wanted=DEFAULT_CHECKPOINT, picked=options[0],
        available=options[:5],
    )
    return options[0], warning


def _round_to_8(n: int) -> int:
    """ComfyUI's KSampler requires width/height multiples of 8."""
    return max(8, ((n + 7) // 8) * 8)


def _choose_gen_size(target_w: int, target_h: int) -> tuple[int, int]:
    """Pick a generation size inside SD 1.5's sweet-spot [GEN_MIN, GEN_MAX].

    Strategy:
      - Square target → clamp side into [GEN_MIN, GEN_MAX].
      - Aspect target → preserve ratio while pushing the **short side**
        up to GEN_MIN, then cap the **long side** at GEN_MAX (capping
        wins if the resulting aspect would require >GEN_MAX on the long
        side, e.g. a 1:5 strip lands at 512×1024 not 512×2560).

    Net effect: every generation runs at >= GEN_MIN on the short side
    so SD 1.5 doesn't produce noise, and <= GEN_MAX on the long side so
    VRAM stays bounded. PIL resize after generation snaps to the exact
    contract dims.
    """
    if target_w == target_h:
        side = max(GEN_MIN, min(GEN_MAX, target_w))
        return _round_to_8(side), _round_to_8(side)

    short_side = min(target_w, target_h)
    long_side = max(target_w, target_h)
    # Scale so the SHORT side hits GEN_MIN minimum.
    scale_to_min = GEN_MIN / short_side if short_side < GEN_MIN else 1.0
    # But cap the LONG side at GEN_MAX.
    scale_to_max = GEN_MAX / long_side if long_side > GEN_MAX else float("inf")
    # If both constraints conflict (e.g. very tall aspect), GEN_MAX wins
    # so we never exceed VRAM.
    scale = min(scale_to_min, scale_to_max)
    # When target is already inside the band, scale stays 1.
    if scale == float("inf"):
        scale = 1.0
    gw = _round_to_8(int(target_w * scale))
    gh = _round_to_8(int(target_h * scale))
    return gw, gh


def _build_txt2img_workflow(
    *,
    checkpoint: str,
    positive_prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int = 20,
    cfg: float = 6.5,
    sampler: str = "euler",
    scheduler: str = "normal",
    filename_prefix: str = "_mycrew_gen",
    background_mode: str = "opaque",
) -> dict:
    """Build a ComfyUI workflow JSON.

    `background_mode` (2026-05-20):
      - `"opaque"`: vanilla txt2img + SaveImage (RGB) — historical default
      - `"pixel_pil"`: same as opaque inside ComfyUI — the alpha is added
        post-hoc by `_pil_remove_solid_bg` after the script downloads
        the PNG. Suitable for pixel art / flat-color subjects where the
        background is uniform and ComfyUI's neural mattes would
        introduce edge blur.
      - `"ai_node"`: chain `RemoveBackground` after VAEDecode + use
        `SaveImageWithAlpha` so the saved PNG already carries an alpha
        channel. Suitable for photoreal / complex-subject images where
        the background isn't a solid color.

    All modes share node ids 3-7 (sampler/checkpoint/latent/CLIP) so a
    user opening the history entry in ComfyUI's web UI sees a familiar
    layout. The post-decode tail differs: opaque/pixel_pil end at
    `9 = SaveImage`; ai_node uses
    `10 = RemoveBackground` + `11 = SaveImageWithAlpha`.
    """
    base: dict = {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": sampler, "scheduler": scheduler,
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {
            "ckpt_name": checkpoint,
        }},
        "5": {"class_type": "EmptyLatentImage", "inputs": {
            "width": width, "height": height, "batch_size": 1,
        }},
        "6": {"class_type": "CLIPTextEncode", "inputs": {
            "text": positive_prompt, "clip": ["4", 1],
        }},
        "7": {"class_type": "CLIPTextEncode", "inputs": {
            "text": negative_prompt, "clip": ["4", 1],
        }},
        "8": {"class_type": "VAEDecode", "inputs": {
            "samples": ["3", 0], "vae": ["4", 2],
        }},
    }
    if background_mode == "ai_node":
        # RemoveBackground takes an IMAGE and outputs IMAGE,MASK. The
        # downstream node we use is SaveImageWithAlpha which takes
        # (images, mask) — exactly the pair we get out of slot [0,1].
        base["10"] = {"class_type": "RemoveBackground", "inputs": {
            "image": ["8", 0],
        }}
        base["11"] = {"class_type": "SaveImageWithAlpha", "inputs": {
            "images": ["10", 0],
            "mask": ["10", 1],
            "filename_prefix": filename_prefix,
        }}
    else:
        base["9"] = {"class_type": "SaveImage", "inputs": {
            "images": ["8", 0],
            "filename_prefix": filename_prefix,
        }}
    return base


def _pil_remove_solid_bg(img_bytes: bytes, *, tolerance: int = 12) -> bytes:
    """Convert an RGB PNG to RGBA by detecting and erasing the solid
    background color.

    Algorithm:
      1. Sample the 4 corner pixels — the majority color is "the
         background" (works on pixel art / flat-color subjects where the
         background is a uniform plate).
      2. For every pixel within `tolerance` Manhattan distance of the
         majority color, set alpha=0.
      3. Return PNG bytes.

    This is intentionally simpler than a neural matte (rembg / BRIA) —
    pixel art has hard edges and uniform backgrounds, so a threshold
    works perfectly and avoids the blur that ML mattes introduce on
    small images.

    For complex backgrounds (gradients, patterns) the caller should pick
    background_mode='ai_node' instead.
    """
    from io import BytesIO
    from collections import Counter
    from PIL import Image

    with Image.open(BytesIO(img_bytes)) as im:
        rgba = im.convert("RGBA")
        w, h = rgba.size
        if w < 2 or h < 2:
            # Too small for a corner sample — just bail and return the
            # original bytes; caller decides what to do.
            buf = BytesIO()
            rgba.save(buf, "PNG")
            return buf.getvalue()
        px = rgba.load()
        corners = [
            px[0, 0][:3],
            px[w - 1, 0][:3],
            px[0, h - 1][:3],
            px[w - 1, h - 1][:3],
        ]
        # Majority corner color (ties → first occurrence).
        bg_color = Counter(corners).most_common(1)[0][0]
        # Single-pass alpha erase by Manhattan distance.
        bg_r, bg_g, bg_b = bg_color
        for y in range(h):
            for x in range(w):
                r, g, b, _a = px[x, y]
                d = abs(r - bg_r) + abs(g - bg_g) + abs(b - bg_b)
                if d <= tolerance * 3:
                    px[x, y] = (r, g, b, 0)
        buf = BytesIO()
        rgba.save(buf, "PNG")
        return buf.getvalue()


async def _enqueue(client: httpx.AsyncClient, workflow: dict) -> str:
    resp = await _http_post(client, "/prompt", {"prompt": workflow})
    body = resp.json()
    if body.get("node_errors"):
        raise ComfyHttpError(
            f"ComfyUI rejected workflow: {body['node_errors']}"
        )
    prompt_id = body.get("prompt_id")
    if not prompt_id:
        raise ComfyHttpError(f"ComfyUI /prompt missing prompt_id: {body}")
    return prompt_id


async def _wait_for_history(
    client: httpx.AsyncClient, prompt_id: str, *, timeout_sec: float,
) -> dict:
    """Poll /history/<prompt_id> until ComfyUI finishes the job or
    the timeout fires. Returns the outputs map (node_id → list of
    image dicts) from the history record."""
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/history/{prompt_id}")
        if resp.status_code == 200:
            j = resp.json()
            rec = j.get(prompt_id) if isinstance(j, dict) else None
            if rec and rec.get("outputs"):
                # Surface any per-node errors before claiming success.
                status = rec.get("status") or {}
                if status.get("status_str") == "error":
                    messages = status.get("messages") or []
                    raise ComfyHttpError(
                        f"ComfyUI job errored: {messages[-3:] if messages else 'no detail'}"
                    )
                return rec["outputs"]
        await asyncio.sleep(POLL_INTERVAL_SEC)
    raise ComfyHttpError(
        f"ComfyUI job {prompt_id} did not complete within {timeout_sec}s"
    )


async def _fetch_image_bytes(
    client: httpx.AsyncClient, *, filename: str, subfolder: str, type_: str,
) -> bytes:
    """Pull the rendered PNG from ComfyUI's /view endpoint. ComfyUI
    writes the file to its output_directory on disk too — but reading
    via HTTP keeps this module path-agnostic (it doesn't need to know
    where ComfyUI's outputs/ lives)."""
    params = {"filename": filename, "subfolder": subfolder, "type": type_}
    resp = await client.get("/view", params=params)
    if resp.status_code != 200:
        raise ComfyHttpError(
            f"/view failed: {resp.status_code} {resp.text[:120]}"
        )
    return resp.content


# ── Prompt spec extraction ────────────────────────────────────────


def _slug(text: str, max_len: int = 24) -> str:
    """Filesystem-safe slug for the ComfyUI temp filename prefix."""
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text or "out")
    return s[:max_len].strip("_") or "out"


def _extract_dims_from_schema(schema: dict) -> tuple[int | None, int | None]:
    """Pull (width, height) from a PM output_schema. Accepts three
    increasingly forgiving shapes:

      1. `properties.width.const = 64` (PM v5 preferred — strict)
      2. `properties.width.examples = [64]` (PM v4 fallback)
      3. `properties.width.description = '像素宽，64'` — rescue path
         (2026-05-20): PM Phase 5 LLM sometimes pins the dimension in
         description prose instead of using const/examples. Falling
         back to a regex over the description text rescues that case
         instead of failing the whole task because the schema author
         was sloppy.
    """
    if not isinstance(schema, dict):
        return None, None
    props = schema.get("properties")
    if not isinstance(props, dict):
        return None, None

    def read(key: str) -> int | None:
        spec = props.get(key)
        if not isinstance(spec, dict):
            return None
        if isinstance(spec.get("const"), int):
            return spec["const"]
        ex = spec.get("examples")
        if isinstance(ex, list) and ex and isinstance(ex[0], int):
            return ex[0]
        # Description fallback: find the first plausible integer
        # in the description text. Stays conservative — only fires
        # when const/examples are absent, and rejects values < 8 or
        # > 8192 (out of ComfyUI's reasonable range, almost certainly
        # not a pixel dim).
        desc = spec.get("description")
        if isinstance(desc, str):
            for match in re.finditer(r"(\d{2,5})", desc):
                n = int(match.group(1))
                if 8 <= n <= 8192:
                    return n
        return None

    return read("width"), read("height")


def _spec_for_path(head_spec: dict, rel_path: str) -> dict:
    """Pull this child's per-path entry out of Head's emit_output.

    Accepted shapes (in priority order):
      1. head_spec.prompts[<rel_path>] = {positive_prompt, negative_prompt,
         seed, [steps, cfg, sampler, scheduler, denoise, checkpoint]}
         — per-path override of any node param
      2. head_spec.prompts (single-task case) used directly
      3. fallback: synthesize from Head's style + palette + filename stem
    """
    if not isinstance(head_spec, dict):
        head_spec = {}
    prompts = head_spec.get("prompts")
    if isinstance(prompts, dict) and rel_path in prompts and isinstance(prompts[rel_path], dict):
        return prompts[rel_path]
    if isinstance(prompts, dict) and {"positive_prompt", "negative_prompt"} & set(prompts.keys()):
        return prompts
    # Fallback — Head didn't enumerate this path. Compose a usable spec
    # from style/palette + filename so the run still produces something.
    style = head_spec.get("style") or ""
    palette = head_spec.get("palette") or []
    palette_str = ", ".join(str(c) for c in palette[:6])
    stem = Path(rel_path).stem
    return {
        "positive_prompt": (
            f"{stem}, {style}, color palette {palette_str}".strip(", ")
            or stem
        ),
        "negative_prompt": (
            "blurry, low quality, watermark, signature, text, multiple subjects"
        ),
        "seed": 12345,
    }


_NODE_PARAM_KEYS = ("checkpoint", "steps", "cfg", "sampler", "scheduler", "denoise")


def _resolve_node_params(head_spec: dict | None, path_spec: dict) -> dict:
    """Merge node params from three sources, narrowest-wins:

        1. DEFAULT_NODE_PARAMS (script-level safety net)
        2. head_spec.model (Head's project-wide model choice + sampler config)
        3. head_spec top-level (LLM-flat shape — same keys at root)
        4. path_spec (per-image overrides from prompts[<path>])

    Each later layer unconditionally overrides earlier ones for the
    keys it carries. Recognised keys: checkpoint, steps, cfg, sampler,
    scheduler, denoise.

    Head can either nest the model params under `model: {...}` or put
    them at the root (`steps`, `cfg`, ...). LLMs are inconsistent about
    nesting so we accept both shapes; if both are present, per-key
    last-write-wins (root shadows model).
    """
    out: dict = dict(DEFAULT_NODE_PARAMS)
    head = head_spec or {}

    # Layer 2: explicit model bundle.
    model = head.get("model")
    if isinstance(model, dict):
        for k in _NODE_PARAM_KEYS:
            if k in model:
                out[k] = model[k]

    # Layer 3: top-level shadow (LLM-flat shape).
    for k in _NODE_PARAM_KEYS:
        if k in head:
            out[k] = head[k]

    # Layer 4: per-path overrides — the narrowest scope always wins.
    for k in _NODE_PARAM_KEYS:
        if k in path_spec:
            out[k] = path_spec[k]
    return out


# ── Main entry ────────────────────────────────────────────────────


async def generate_image_for_child(
    *,
    child_task_row: dict,
    head_spec: dict | None,
    project_root: str,
    base_url: str = DEFAULT_BASE_URL,
) -> dict:
    """Generate one image deterministically for a single fan-out child.

    Returns an emit_output-shaped dict so downstream (workflow_svc fan-out
    aggregator + script QA) sees the same contract whether the step was
    LLM-driven or script-driven.
    """
    output_paths = _parse_json_list(child_task_row.get("output_paths"))
    if not output_paths:
        return _fail("child task has empty output_paths")
    rel_path = output_paths[0]

    schema = _parse_json_dict(child_task_row.get("output_schema"))
    exp_w, exp_h = _extract_dims_from_schema(schema)
    if exp_w is None or exp_h is None:
        return _fail(
            f"output_schema 缺 width/height const，无法决定生成尺寸 "
            f"(rel_path={rel_path})"
        )

    if not project_root:
        return _fail("project root_path 未配置，无法落盘 PNG")

    spec = _spec_for_path(head_spec or {}, rel_path)

    # 2026-05-20 image-flow v2: PromptSmith outputs `subject_prompt` (per
    # image), project-level StyleArchitect outputs `art_style_spec`
    # (carried in head_spec). Final positive prompt = "{style}, {subject}".
    # Backward-compat: legacy heads still send `positive_prompt` directly
    # — we honour that when neither style nor subject is present.
    art_style_spec = (head_spec or {}).get("art_style_spec") if isinstance(head_spec, dict) else None
    style_prompt = ""
    fallback_style = ""
    background_mode = "opaque"
    if isinstance(art_style_spec, dict):
        style_prompt = str(art_style_spec.get("style_prompt") or "").strip()
        fallback_style = str(art_style_spec.get("fallback_style_prompt") or "").strip()
        bm = str(art_style_spec.get("background_mode") or "").strip().lower()
        if bm in ("pixel_pil", "ai_node", "opaque"):
            background_mode = bm

    subject_prompt = str(spec.get("subject_prompt") or "").strip()
    legacy_positive = str(spec.get("positive_prompt") or "").strip()

    # Compose final positive. style first (matters for SD prompt weighting
    # — leading tokens are stronger), subject second.
    if subject_prompt:
        effective_style = style_prompt or fallback_style
        positive = (
            f"{effective_style}, {subject_prompt}" if effective_style
            else subject_prompt
        )
    elif legacy_positive:
        positive = legacy_positive
    else:
        return _fail(
            f"head_spec 既没给 {rel_path} 的 subject_prompt（新格式）"
            "也没给 positive_prompt（legacy）；同时 style_prompt 也空——"
            "无 prompt 可用，拒绝生成"
        )

    negative = str(spec.get("negative_prompt") or "").strip()
    seed_raw = spec.get("seed")
    try:
        seed = int(seed_raw) if seed_raw is not None else 12345
    except (TypeError, ValueError):
        seed = 12345

    # Per-path background_mode override (a task can opt into a different
    # mode than the project default — e.g. one UI icon needs alpha when
    # the rest of the project is opaque).
    path_bm = str(spec.get("background_mode") or "").strip().lower()
    if path_bm in ("pixel_pil", "ai_node", "opaque"):
        background_mode = path_bm

    # Resolve node parameters from Head's choices (project-wide model
    # + per-path overrides). All but `checkpoint` are passed straight
    # through to the workflow builder; checkpoint goes through
    # `_resolve_checkpoint` for availability verification.
    node_params = _resolve_node_params(head_spec, spec)
    # art_style_spec.checkpoint also gets folded in as a fallback layer
    # between path_spec and DEFAULT_CHECKPOINT.
    if "checkpoint" not in node_params and isinstance(art_style_spec, dict):
        style_ckpt = art_style_spec.get("checkpoint")
        if isinstance(style_ckpt, str) and style_ckpt:
            node_params["checkpoint"] = style_ckpt
    requested_checkpoint = node_params.pop("checkpoint", None)

    gen_w, gen_h = _choose_gen_size(exp_w, exp_h)
    prefix = "_mycrew_" + _slug(Path(rel_path).stem)
    issues: list[str] = []

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
            checkpoint, ckpt_warning = await _resolve_checkpoint(
                client, preferred=requested_checkpoint,
            )
            if ckpt_warning:
                issues.append(f"[warning] {ckpt_warning}")
            workflow = _build_txt2img_workflow(
                checkpoint=checkpoint,
                positive_prompt=positive,
                negative_prompt=negative,
                width=gen_w, height=gen_h,
                seed=seed,
                steps=int(node_params.get("steps") or DEFAULT_NODE_PARAMS["steps"]),
                cfg=float(node_params.get("cfg") or DEFAULT_NODE_PARAMS["cfg"]),
                sampler=str(node_params.get("sampler") or DEFAULT_NODE_PARAMS["sampler"]),
                scheduler=str(node_params.get("scheduler") or DEFAULT_NODE_PARAMS["scheduler"]),
                filename_prefix=prefix,
                background_mode=background_mode,
            )
            prompt_id = await _enqueue(client, workflow)
            log.info(
                "image_gen.enqueued",
                prompt_id=prompt_id, rel_path=rel_path,
                gen_w=gen_w, gen_h=gen_h, checkpoint=checkpoint,
            )
            outputs = await _wait_for_history(
                client, prompt_id, timeout_sec=GEN_TIMEOUT_SEC,
            )
            save_node = outputs.get("9") or next(iter(outputs.values()))
            images = (save_node or {}).get("images") or []
            if not images:
                return _fail(
                    f"ComfyUI 完成但 SaveImage 输出为空 (prompt_id={prompt_id})"
                )
            img_meta = images[0]
            img_bytes = await _fetch_image_bytes(
                client,
                filename=img_meta["filename"],
                subfolder=img_meta.get("subfolder", ""),
                type_=img_meta.get("type", "output"),
            )
    except ComfyHttpError as exc:
        log.warning("image_gen.comfy_error", rel_path=rel_path, error=str(exc))
        return _fail(f"ComfyUI 调用失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        log.error("image_gen.unexpected_error", rel_path=rel_path, error=str(exc))
        return _fail(f"图像生成异常：{exc}")

    # Save to disk at the contract path (resize to exact target).
    # background_mode dictates post-processing:
    #   - opaque: vanilla RGB → resize → save
    #   - pixel_pil: corner-color → alpha → resize → save (RGBA)
    #   - ai_node: ComfyUI already returned an RGBA PNG from
    #     SaveImageWithAlpha; just resize (preserving alpha) + save
    abs_path = Path(project_root) / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from io import BytesIO
        from PIL import Image
        if background_mode == "pixel_pil":
            img_bytes = _pil_remove_solid_bg(img_bytes)
        img = Image.open(BytesIO(img_bytes))
        if (img.width, img.height) != (exp_w, exp_h):
            # Resampling — when the image has an alpha channel
            # (pixel_pil / ai_node), LANCZOS bleeds the transparent
            # edges; NEAREST preserves hard pixel edges typical of
            # game sprites. We pick NEAREST only when alpha is
            # present AND target is downscale-small (pixel-art-ish).
            has_alpha = img.mode in ("RGBA", "LA", "PA")
            small_target = max(exp_w, exp_h) <= 256
            if has_alpha and small_target:
                img = img.resize((exp_w, exp_h), Image.NEAREST)
            else:
                img = img.resize((exp_w, exp_h), Image.LANCZOS)
        img.save(abs_path, "PNG")
    except Exception as exc:  # noqa: BLE001
        log.error("image_gen.save_failed", rel_path=rel_path, error=str(exc))
        return _fail(f"图像落盘失败：{exc}")

    log.info(
        "image_gen.completed",
        rel_path=rel_path, target=f"{exp_w}x{exp_h}",
        generated=f"{gen_w}x{gen_h}",
        checkpoint=checkpoint,
        background_mode=background_mode,
        steps=node_params.get("steps"),
        cfg=node_params.get("cfg"),
        sampler=node_params.get("sampler"),
        scheduler=node_params.get("scheduler"),
    )
    return {
        "verdict": "pass",
        "file_paths": [rel_path],
        "width": exp_w,
        "height": exp_h,
        "issues": issues,
        "summary": (
            f"生成 {rel_path} ({gen_w}x{gen_h} → 缩放 {exp_w}x{exp_h}); "
            f"checkpoint={checkpoint}, seed={seed}, "
            f"bg={background_mode}, "
            f"steps={node_params.get('steps')}, cfg={node_params.get('cfg')}, "
            f"sampler={node_params.get('sampler')}/{node_params.get('scheduler')}"
        ),
    }


# ── Helpers ───────────────────────────────────────────────────────


def _fail(msg: str) -> dict:
    return {
        "verdict": "fail",
        "file_paths": [],
        "issues": [msg],
        "summary": "脚本生成失败",
    }


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
