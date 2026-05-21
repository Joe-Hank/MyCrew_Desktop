"""Tests for services.image_gen_script — deterministic ComfyUI image
generation (Stage 3 replacement of LLM Generator step).

ComfyUI HTTP itself is mocked via `httpx.MockTransport` so the tests
don't need a real server. Coverage:
  - Size clamp/round helpers
  - Head-spec extraction (per-path map / fallback / single-task shape)
  - Workflow JSON shape (input wiring, params from head_spec)
  - End-to-end happy path (mocked /prompt + /history + /view)
  - Failure modes (no checkpoint installed, ComfyUI 5xx, missing dims)
"""
from __future__ import annotations

import io
import json
import re
from typing import Any

import httpx
import pytest
from PIL import Image

from services import image_gen_script


# ── Pure helpers ─────────────────────────────────────────────────


@pytest.mark.parametrize("target,expected", [
    ((64, 64), (512, 512)),       # too small → clamp up to GEN_MIN
    ((512, 512), (512, 512)),     # in sweet spot
    ((768, 768), (768, 768)),
    ((1080, 1080), (1024, 1024)),  # too large → clamp down to GEN_MAX
    ((100, 200), (512, 1024)),     # aspect preserved
    ((1500, 750), (1024, 512)),
])
def test_choose_gen_size(target, expected):
    w, h = image_gen_script._choose_gen_size(*target)
    assert (w, h) == expected


def test_round_to_8():
    assert image_gen_script._round_to_8(63) == 64
    assert image_gen_script._round_to_8(64) == 64
    assert image_gen_script._round_to_8(65) == 72
    assert image_gen_script._round_to_8(1) == 8


def test_extract_dims_const():
    schema = {"properties": {"width": {"const": 512}, "height": {"const": 768}}}
    assert image_gen_script._extract_dims_from_schema(schema) == (512, 768)


def test_extract_dims_examples_fallback():
    schema = {"properties": {"width": {"examples": [128]}, "height": {"examples": [128]}}}
    assert image_gen_script._extract_dims_from_schema(schema) == (128, 128)


def test_extract_dims_missing():
    assert image_gen_script._extract_dims_from_schema({}) == (None, None)


def test_spec_for_path_keyed_map():
    head = {"prompts": {
        "a.png": {"positive_prompt": "p_a", "negative_prompt": "n_a", "seed": 1},
        "b.png": {"positive_prompt": "p_b", "negative_prompt": "n_b", "seed": 2},
    }}
    out = image_gen_script._spec_for_path(head, "b.png")
    assert out["positive_prompt"] == "p_b"
    assert out["seed"] == 2


def test_spec_for_path_single_task_flat_prompts():
    """Single-task case: head.prompts is the spec directly, not a per-
    path map. Treat the whole dict as this child's spec."""
    head = {"prompts": {
        "positive_prompt": "p", "negative_prompt": "n", "seed": 42,
    }}
    out = image_gen_script._spec_for_path(head, "anything.png")
    assert out["positive_prompt"] == "p"


def test_spec_for_path_fallback_from_style():
    """No prompts map at all → synthesize from style+palette+filename."""
    head = {"style": "黑袍纠察队美漫风", "palette": ["#1C1C1C", "#C0392B"]}
    out = image_gen_script._spec_for_path(head, "Assets/Butcher_64.png")
    assert "Butcher_64" in out["positive_prompt"]
    assert "黑袍纠察队美漫风" in out["positive_prompt"]
    # Negative is the standard avoidance list
    assert "blurry" in out["negative_prompt"]


def test_build_txt2img_workflow_wires_prompts():
    wf = image_gen_script._build_txt2img_workflow(
        checkpoint="ck.safetensors",
        positive_prompt="P", negative_prompt="N",
        width=512, height=768, seed=7,
    )
    # Positive prompt lives on node "6"
    assert wf["6"]["inputs"]["text"] == "P"
    # Negative on "7"
    assert wf["7"]["inputs"]["text"] == "N"
    # Latent has the dims
    assert wf["5"]["inputs"]["width"] == 512
    assert wf["5"]["inputs"]["height"] == 768
    # Checkpoint pinned
    assert wf["4"]["inputs"]["ckpt_name"] == "ck.safetensors"
    # KSampler seed
    assert wf["3"]["inputs"]["seed"] == 7


# ── End-to-end with mocked httpx ──────────────────────────────────


def _make_fake_comfyui(
    *, checkpoints: list[str], img_bytes: bytes, prompt_id: str = "fake-id",
    error_at: str | None = None,
):
    """Build an httpx MockTransport that mimics the ComfyUI endpoints
    image_gen_script touches. `error_at` injects a 500 at a specific
    path to exercise the failure branch."""
    history_call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if error_at and path.startswith(error_at):
            return httpx.Response(500, text="boom")
        if path == "/object_info/CheckpointLoaderSimple":
            body = {"CheckpointLoaderSimple": {
                "input": {"required": {"ckpt_name": [checkpoints]}},
            }}
            return httpx.Response(200, json=body)
        if path == "/prompt":
            return httpx.Response(
                200, json={"prompt_id": prompt_id, "node_errors": {}},
            )
        if path.startswith("/history/"):
            history_call_count["n"] += 1
            # First call → still running (empty). Second → completed.
            if history_call_count["n"] < 2:
                return httpx.Response(200, json={})
            return httpx.Response(200, json={
                prompt_id: {
                    "outputs": {"9": {"images": [{
                        "filename": "_mycrew_test_00001_.png",
                        "subfolder": "",
                        "type": "output",
                    }]}},
                    "status": {"status_str": "success"},
                },
            })
        if path == "/view":
            return httpx.Response(200, content=img_bytes)
        return httpx.Response(404, text=f"unmocked: {path}")

    return httpx.MockTransport(handler)


def _png_bytes(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h), (123, 45, 67))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_generate_image_for_child_happy_path(tmp_path, monkeypatch):
    transport = _make_fake_comfyui(
        checkpoints=["majicmixRealistic_v7.safetensors", "other.safetensors"],
        img_bytes=_png_bytes(512, 512),
    )
    # Patch the AsyncClient constructor in the module so it uses our
    # transport regardless of base_url.
    real_client = httpx.AsyncClient

    def patched(base_url=None, **kw):
        return real_client(transport=transport, base_url=base_url or "http://x")

    monkeypatch.setattr(image_gen_script.httpx, "AsyncClient", patched)
    # Tighten poll interval so the test doesn't wait 2s.
    monkeypatch.setattr(image_gen_script, "POLL_INTERVAL_SEC", 0.01)

    child = {
        "id": "c1",
        "output_paths": json.dumps(["Assets/Sprites/foo.png"]),
        "output_schema": json.dumps({"properties": {
            "width": {"const": 64}, "height": {"const": 64},
        }}),
    }
    head_spec = {"prompts": {
        "Assets/Sprites/foo.png": {
            "positive_prompt": "Butcher portrait",
            "negative_prompt": "blurry",
            "seed": 9,
        },
    }}
    root = tmp_path / "workspace"
    root.mkdir()

    result = await image_gen_script.generate_image_for_child(
        child_task_row=child, head_spec=head_spec, project_root=str(root),
    )

    assert result["verdict"] == "pass", result
    assert result["file_paths"] == ["Assets/Sprites/foo.png"]
    assert result["width"] == 64 and result["height"] == 64
    # File landed on disk + resized to exact target dims
    final = root / "Assets/Sprites/foo.png"
    assert final.exists()
    with Image.open(final) as got:
        assert got.size == (64, 64)


@pytest.mark.asyncio
async def test_generate_image_for_child_no_checkpoints(tmp_path, monkeypatch):
    transport = _make_fake_comfyui(
        checkpoints=[],
        img_bytes=b"",
    )
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        image_gen_script.httpx, "AsyncClient",
        lambda base_url=None, **kw: real_client(transport=transport, base_url=base_url or "http://x"),
    )
    child = {
        "id": "c1",
        "output_paths": json.dumps(["a.png"]),
        "output_schema": json.dumps({"properties": {
            "width": {"const": 512}, "height": {"const": 512},
        }}),
    }
    result = await image_gen_script.generate_image_for_child(
        child_task_row=child,
        head_spec={"prompts": {"a.png": {"positive_prompt": "x", "negative_prompt": "y"}}},
        project_root=str(tmp_path),
    )
    assert result["verdict"] == "fail"
    assert any("checkpoint" in i.lower() for i in result["issues"])


@pytest.mark.asyncio
async def test_generate_image_for_child_missing_dims():
    """schema without width/height const → must fail with diagnostic,
    NEVER guess."""
    child = {
        "id": "c1",
        "output_paths": json.dumps(["a.png"]),
        "output_schema": json.dumps({"properties": {}}),
    }
    result = await image_gen_script.generate_image_for_child(
        child_task_row=child, head_spec={}, project_root="/x",
    )
    assert result["verdict"] == "fail"
    assert any("width/height" in i for i in result["issues"])


@pytest.mark.asyncio
async def test_generate_image_for_child_empty_output_paths():
    result = await image_gen_script.generate_image_for_child(
        child_task_row={"id": "c1", "output_paths": "[]"},
        head_spec={}, project_root="/x",
    )
    assert result["verdict"] == "fail"
    assert "empty output_paths" in result["issues"][0]


def test_spec_for_path_fallback_when_head_spec_is_none():
    """Tested at the spec-extraction layer (not the full pipeline) to
    avoid making a real ComfyUI HTTP call when no mock is wired."""
    out = image_gen_script._spec_for_path(None, "a.png")  # type: ignore[arg-type]
    # _spec_for_path coerces non-dict to {} then synthesizes stem-only
    # positive prompt. Verifies graceful degradation.
    assert out["positive_prompt"]
    assert "a" in out["positive_prompt"]
    assert out["negative_prompt"]


@pytest.mark.asyncio
async def test_generate_image_for_child_no_root_path():
    child = {
        "id": "c1",
        "output_paths": json.dumps(["a.png"]),
        "output_schema": json.dumps({"properties": {
            "width": {"const": 64}, "height": {"const": 64},
        }}),
    }
    result = await image_gen_script.generate_image_for_child(
        child_task_row=child,
        head_spec={"prompts": {"a.png": {"positive_prompt": "x"}}},
        project_root="",
    )
    assert result["verdict"] == "fail"
    assert any("root_path" in i for i in result["issues"])


@pytest.mark.asyncio
async def test_generate_image_for_child_comfy_5xx(tmp_path, monkeypatch):
    """Server 500 on /prompt → captured fail with the upstream message."""
    transport = _make_fake_comfyui(
        checkpoints=["ck.safetensors"],
        img_bytes=b"",
        error_at="/prompt",
    )
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        image_gen_script.httpx, "AsyncClient",
        lambda base_url=None, **kw: real_client(transport=transport, base_url=base_url or "http://x"),
    )

    child = {
        "id": "c1",
        "output_paths": json.dumps(["a.png"]),
        "output_schema": json.dumps({"properties": {
            "width": {"const": 512}, "height": {"const": 512},
        }}),
    }
    result = await image_gen_script.generate_image_for_child(
        child_task_row=child,
        head_spec={"prompts": {"a.png": {"positive_prompt": "x"}}},
        project_root=str(tmp_path),
    )
    assert result["verdict"] == "fail"
    assert any("ComfyUI" in i for i in result["issues"])


# Suppress unused-imports lint
_ = re
_ = Any


# ── Node parameter resolution (Head's full creative spec) ─────────

def test_resolve_node_params_defaults_only():
    """No head_spec, no path_spec → fall back to DEFAULT_NODE_PARAMS."""
    out = image_gen_script._resolve_node_params(None, {})
    assert out["steps"] == 20
    assert out["sampler"] == "euler"
    assert out["scheduler"] == "normal"
    assert "checkpoint" not in out  # checkpoint resolved separately


def test_resolve_node_params_model_bundle_wins():
    """When Head sends `model: {...}`, those fields override defaults."""
    head = {"model": {
        "checkpoint": "cyberpunk.safetensors",
        "steps": 30, "cfg": 7.5,
        "sampler": "dpmpp_2m", "scheduler": "karras",
    }}
    out = image_gen_script._resolve_node_params(head, {})
    assert out["checkpoint"] == "cyberpunk.safetensors"
    assert out["steps"] == 30
    assert out["cfg"] == 7.5
    assert out["sampler"] == "dpmpp_2m"
    assert out["scheduler"] == "karras"


def test_resolve_node_params_top_level_shadow():
    """LLMs sometimes flatten — accept fields at head_spec root if no
    model bundle is given."""
    head = {
        "checkpoint": "FireRed-Lightning.safetensors",
        "steps": 8, "cfg": 2.0, "sampler": "euler", "scheduler": "sgm_uniform",
    }
    out = image_gen_script._resolve_node_params(head, {})
    assert out["checkpoint"] == "FireRed-Lightning.safetensors"
    assert out["steps"] == 8
    assert out["cfg"] == 2.0


def test_resolve_node_params_per_path_override():
    """Per-image overrides beat project-wide model bundle."""
    head = {"model": {"checkpoint": "global.safetensors", "steps": 20}}
    path = {"steps": 40, "cfg": 9.0}
    out = image_gen_script._resolve_node_params(head, path)
    # path-level wins on overridden keys
    assert out["steps"] == 40
    assert out["cfg"] == 9.0
    # global retained for keys path didn't touch
    assert out["checkpoint"] == "global.safetensors"


def test_resolve_node_params_per_path_can_swap_checkpoint():
    """Per-path checkpoint override is allowed — e.g. one image needs a
    different aesthetic from the project default."""
    head = {"model": {"checkpoint": "realistic.safetensors"}}
    path = {"checkpoint": "anime.safetensors"}
    out = image_gen_script._resolve_node_params(head, path)
    assert out["checkpoint"] == "anime.safetensors"


@pytest.mark.asyncio
async def test_resolve_checkpoint_honours_head_preference(tmp_path, monkeypatch):
    """When Head specified a checkpoint that IS installed, use it; no
    warning emitted."""
    transport = _make_fake_comfyui(
        checkpoints=["foo.safetensors", "bar.safetensors"],
        img_bytes=b"",
    )
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        image_gen_script.httpx, "AsyncClient",
        lambda base_url=None, **kw: real_client(transport=transport, base_url=base_url or "http://x"),
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as c:
        picked, warning = await image_gen_script._resolve_checkpoint(
            c, preferred="bar.safetensors",
        )
    assert picked == "bar.safetensors"
    assert warning is None


@pytest.mark.asyncio
async def test_resolve_checkpoint_falls_back_with_warning(monkeypatch):
    """Head asked for X.safetensors, only Y / Z installed → pick the
    fallback (DEFAULT_CHECKPOINT if present, else first) AND surface a
    warning string so the user sees what actually ran."""
    transport = _make_fake_comfyui(
        checkpoints=["majicmixRealistic_v7.safetensors", "z.safetensors"],
        img_bytes=b"",
    )
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        image_gen_script.httpx, "AsyncClient",
        lambda base_url=None, **kw: real_client(transport=transport, base_url=base_url or "http://x"),
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://x") as c:
        picked, warning = await image_gen_script._resolve_checkpoint(
            c, preferred="totally_missing_model.safetensors",
        )
    assert picked == "majicmixRealistic_v7.safetensors"  # DEFAULT_CHECKPOINT
    assert warning is not None
    assert "totally_missing_model" in warning


@pytest.mark.asyncio
async def test_generate_image_for_child_uses_head_node_params(tmp_path, monkeypatch):
    """Head's model bundle (sampler / steps / cfg / scheduler) must
    actually land in the workflow JSON sent to ComfyUI. Captures the
    /prompt request body and asserts the KSampler node uses Head's
    choices, not script defaults."""
    captured_workflow: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/object_info/CheckpointLoaderSimple":
            return httpx.Response(200, json={"CheckpointLoaderSimple": {
                "input": {"required": {"ckpt_name": [["cyberpunk.safetensors"]]}},
            }})
        if path == "/prompt":
            captured_workflow.update(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": "pid", "node_errors": {}})
        if path.startswith("/history/"):
            return httpx.Response(200, json={"pid": {
                "outputs": {"9": {"images": [{
                    "filename": "x.png", "subfolder": "", "type": "output",
                }]}},
                "status": {"status_str": "success"},
            }})
        if path == "/view":
            return httpx.Response(200, content=_png_bytes(512, 512))
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        image_gen_script.httpx, "AsyncClient",
        lambda base_url=None, **kw: real_client(transport=transport, base_url=base_url or "http://x"),
    )
    monkeypatch.setattr(image_gen_script, "POLL_INTERVAL_SEC", 0.01)

    child = {
        "id": "c1",
        "output_paths": json.dumps(["x.png"]),
        "output_schema": json.dumps({"properties": {
            "width": {"const": 512}, "height": {"const": 512},
        }}),
    }
    head_spec = {
        "model": {
            "checkpoint": "cyberpunk.safetensors",
            "steps": 35, "cfg": 7.5,
            "sampler": "dpmpp_2m", "scheduler": "karras",
        },
        "prompts": {"x.png": {
            "positive_prompt": "neon city street", "negative_prompt": "blurry",
            "seed": 999,
        }},
    }
    result = await image_gen_script.generate_image_for_child(
        child_task_row=child, head_spec=head_spec,
        project_root=str(tmp_path),
    )
    assert result["verdict"] == "pass", result
    # KSampler node carries Head's params verbatim
    ks = captured_workflow["3"]["inputs"]
    assert ks["steps"] == 35
    assert ks["cfg"] == 7.5
    assert ks["sampler_name"] == "dpmpp_2m"
    assert ks["scheduler"] == "karras"
    assert ks["seed"] == 999
    # Checkpoint loader uses Head's pick
    assert captured_workflow["4"]["inputs"]["ckpt_name"] == "cyberpunk.safetensors"
    # No warning in issues since the requested checkpoint was available
    assert result["issues"] == []


# ── Description fallback (PM Phase 5 sometimes pins dim in prose) ──

def test_extract_dims_from_description_chinese():
    """Real-world case from project proj_71430e792524: PM Phase 5
    wrote 'description: 像素宽，64' instead of using const=64."""
    schema = {"properties": {
        "width": {"type": "integer", "minimum": 1, "description": "像素宽，64"},
        "height": {"type": "integer", "minimum": 1, "description": "像素高，256"},
    }}
    assert image_gen_script._extract_dims_from_schema(schema) == (64, 256)


def test_extract_dims_from_description_english():
    schema = {"properties": {
        "width": {"description": "pixel width 1024 wide"},
        "height": {"description": "1024 px tall"},
    }}
    assert image_gen_script._extract_dims_from_schema(schema) == (1024, 1024)


def test_extract_dims_description_rejects_out_of_range():
    """Numbers <8 or >8192 in description are NOT pixel dims — reject."""
    schema = {"properties": {
        "width": {"description": "must be at least 1 pixel"},  # only "1" — too small
        "height": {"description": "around 99999 cool things"},  # too large
    }}
    assert image_gen_script._extract_dims_from_schema(schema) == (None, None)


def test_extract_dims_const_still_wins_over_description():
    """When both const and description present, const wins."""
    schema = {"properties": {
        "width": {"const": 512, "description": "actually 64 in the prose"},
        "height": {"const": 512, "description": "256 maybe"},
    }}
    assert image_gen_script._extract_dims_from_schema(schema) == (512, 512)


# ── Stage B1: transparency dual-path + style/subject composition ──

def test_workflow_opaque_mode_default():
    """Default mode (no background_mode) → SaveImage at node 9, no
    RemoveBackground node."""
    wf = image_gen_script._build_txt2img_workflow(
        checkpoint="c.safetensors",
        positive_prompt="p", negative_prompt="n",
        width=512, height=512, seed=1,
    )
    assert "9" in wf and wf["9"]["class_type"] == "SaveImage"
    assert "10" not in wf
    assert "11" not in wf


def test_workflow_ai_node_mode_adds_remove_bg_chain():
    """ai_node → SaveImageWithAlpha after RemoveBackground."""
    wf = image_gen_script._build_txt2img_workflow(
        checkpoint="c.safetensors",
        positive_prompt="p", negative_prompt="n",
        width=512, height=512, seed=1,
        background_mode="ai_node",
    )
    assert "9" not in wf  # SaveImage replaced
    assert wf["10"]["class_type"] == "RemoveBackground"
    assert wf["10"]["inputs"]["image"] == ["8", 0]  # VAEDecode -> RemoveBg
    assert wf["11"]["class_type"] == "SaveImageWithAlpha"
    assert wf["11"]["inputs"]["images"] == ["10", 0]
    assert wf["11"]["inputs"]["mask"] == ["10", 1]


def test_workflow_pixel_pil_mode_keeps_opaque_inside_comfyui():
    """pixel_pil -> ComfyUI saves RGB; alpha added post-hoc by
    _pil_remove_solid_bg after download. Workflow shape matches opaque."""
    wf = image_gen_script._build_txt2img_workflow(
        checkpoint="c.safetensors",
        positive_prompt="p", negative_prompt="n",
        width=64, height=64, seed=1,
        background_mode="pixel_pil",
    )
    assert wf["9"]["class_type"] == "SaveImage"
    assert "10" not in wf


def test_pil_remove_solid_bg_uniform_white_becomes_transparent():
    """A 32x32 image with uniform white background + a colored center
    should come out RGBA with white pixels alpha=0 and center
    pixels alpha=255."""
    from io import BytesIO
    from PIL import Image

    img = Image.new("RGB", (32, 32), (255, 255, 255))
    for y in range(14, 18):
        for x in range(14, 18):
            img.putpixel((x, y), (255, 0, 0))
    buf = BytesIO()
    img.save(buf, "PNG")
    raw = buf.getvalue()

    out_bytes = image_gen_script._pil_remove_solid_bg(raw)
    out = Image.open(BytesIO(out_bytes))
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0
    assert out.getpixel((15, 15))[3] == 255


def test_pil_remove_solid_bg_handles_tiny_image():
    """1x1 image cannot be sampled at 4 corners -- function should bail
    gracefully and just return the original as PNG bytes."""
    from io import BytesIO
    from PIL import Image
    img = Image.new("RGB", (1, 1), (200, 50, 50))
    buf = BytesIO()
    img.save(buf, "PNG")
    out_bytes = image_gen_script._pil_remove_solid_bg(buf.getvalue())
    out = Image.open(BytesIO(out_bytes))
    assert out.size == (1, 1)


# ── art_style_spec composition (B1's prep for B2) ─────────────────


def _make_fake_comfyui_capturing_prompt(*, captured_workflow,
                                         img_bytes):
    def handler(request):
        path = request.url.path
        if path == "/object_info/CheckpointLoaderSimple":
            return httpx.Response(200, json={"CheckpointLoaderSimple": {
                "input": {"required": {"ckpt_name": [["c.safetensors"]]}},
            }})
        if path == "/prompt":
            captured_workflow.update(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": "pid", "node_errors": {}})
        if path.startswith("/history/"):
            return httpx.Response(200, json={"pid": {
                "outputs": {"9": {"images": [{
                    "filename": "x.png", "subfolder": "", "type": "output",
                }]}},
                "status": {"status_str": "success"},
            }})
        if path == "/view":
            return httpx.Response(200, content=img_bytes)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_generate_composes_style_plus_subject(tmp_path, monkeypatch):
    """When head_spec carries art_style_spec.style_prompt AND
    prompts[path].subject_prompt, the final positive sent to ComfyUI
    is `style, subject` (style first because SD weights leading tokens)."""
    captured = {}
    transport = _make_fake_comfyui_capturing_prompt(
        captured_workflow=captured, img_bytes=_png_bytes(512, 512),
    )
    real = httpx.AsyncClient
    monkeypatch.setattr(
        image_gen_script.httpx, "AsyncClient",
        lambda base_url=None, **kw: real(transport=transport, base_url=base_url or "http://x"),
    )
    monkeypatch.setattr(image_gen_script, "POLL_INTERVAL_SEC", 0.01)

    child = {
        "id": "c1",
        "output_paths": json.dumps(["x.png"]),
        "output_schema": json.dumps({"properties": {
            "width": {"const": 512}, "height": {"const": 512},
        }}),
    }
    head_spec = {
        "art_style_spec": {
            "style_prompt": "pixel art, 16-bit retro game asset",
            "background_mode": "pixel_pil",
        },
        "prompts": {"x.png": {
            "subject_prompt": "Billy Butcher portrait, leather coat",
            "seed": 1,
        }},
    }
    result = await image_gen_script.generate_image_for_child(
        child_task_row=child, head_spec=head_spec,
        project_root=str(tmp_path),
    )
    assert result["verdict"] == "pass", result
    final_positive = captured["6"]["inputs"]["text"]
    assert final_positive.startswith("pixel art, 16-bit retro game asset")
    assert "Billy Butcher" in final_positive


@pytest.mark.asyncio
async def test_generate_falls_back_to_legacy_positive_prompt(tmp_path, monkeypatch):
    """Old-shape head_spec with positive_prompt (no style/subject split)
    still works -- backward compat with pre-image-flow-v2 PMs."""
    captured = {}
    transport = _make_fake_comfyui_capturing_prompt(
        captured_workflow=captured, img_bytes=_png_bytes(512, 512),
    )
    real = httpx.AsyncClient
    monkeypatch.setattr(
        image_gen_script.httpx, "AsyncClient",
        lambda base_url=None, **kw: real(transport=transport, base_url=base_url or "http://x"),
    )
    monkeypatch.setattr(image_gen_script, "POLL_INTERVAL_SEC", 0.01)

    child = {
        "id": "c1",
        "output_paths": json.dumps(["x.png"]),
        "output_schema": json.dumps({"properties": {
            "width": {"const": 512}, "height": {"const": 512},
        }}),
    }
    head_spec = {
        "prompts": {"x.png": {
            "positive_prompt": "legacy direct prompt, photoreal",
            "negative_prompt": "blurry",
            "seed": 1,
        }},
    }
    result = await image_gen_script.generate_image_for_child(
        child_task_row=child, head_spec=head_spec,
        project_root=str(tmp_path),
    )
    assert result["verdict"] == "pass"
    assert captured["6"]["inputs"]["text"] == "legacy direct prompt, photoreal"


@pytest.mark.asyncio
async def test_generate_uses_art_style_checkpoint_when_path_silent(tmp_path, monkeypatch):
    """When path_spec doesn't override checkpoint, art_style_spec.checkpoint
    is used (one layer above DEFAULT_CHECKPOINT)."""
    captured = {}
    def handler(request):
        path = request.url.path
        if path == "/object_info/CheckpointLoaderSimple":
            return httpx.Response(200, json={"CheckpointLoaderSimple": {
                "input": {"required": {"ckpt_name": [["style.safetensors", "cyberpunk.safetensors"]]}},
            }})
        if path == "/prompt":
            captured.update(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": "pid", "node_errors": {}})
        if path.startswith("/history/"):
            return httpx.Response(200, json={"pid": {
                "outputs": {"9": {"images": [{
                    "filename": "x.png", "subfolder": "", "type": "output",
                }]}}, "status": {"status_str": "success"},
            }})
        if path == "/view":
            return httpx.Response(200, content=_png_bytes(512, 512))
        return httpx.Response(404)
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        image_gen_script.httpx, "AsyncClient",
        lambda base_url=None, **kw: real(transport=transport, base_url=base_url or "http://x"),
    )
    monkeypatch.setattr(image_gen_script, "POLL_INTERVAL_SEC", 0.01)

    child = {
        "id": "c1",
        "output_paths": json.dumps(["x.png"]),
        "output_schema": json.dumps({"properties": {
            "width": {"const": 512}, "height": {"const": 512},
        }}),
    }
    head_spec = {
        "art_style_spec": {
            "style_prompt": "isometric pixel art",
            "checkpoint": "style.safetensors",
        },
        "prompts": {"x.png": {"subject_prompt": "knight", "seed": 1}},
    }
    result = await image_gen_script.generate_image_for_child(
        child_task_row=child, head_spec=head_spec,
        project_root=str(tmp_path),
    )
    assert result["verdict"] == "pass"
    assert captured["4"]["inputs"]["ckpt_name"] == "style.safetensors"
