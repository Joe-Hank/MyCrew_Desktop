"""Tests for services.asset_import_script — deterministic Unity asset
import config (Stage 4 replacement of LLM Technical Artist step).

Coverage:
  - Decision rules per file kind (texture / model / audio)
  - Keyword-driven branches (pixel art / normal map / sprite sheet / BGM
    vs SFX / humanoid)
  - File metadata readers (PIL for images, wave for audio)
  - Unity-project detection (skip cleanly on non-Unity roots)
  - End-to-end with mocked Unity MCP
  - Path-escape guard
"""
from __future__ import annotations

import json
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from services import asset_import_script
from tests.conftest import FakeCRUD


# ── Decision rules: textures ──────────────────────────────────────


def test_texture_default_sprite():
    out = asset_import_script.decide_texture_import(
        "Assets/Sprites/foo.png", "角色头像", 512, 512, has_alpha=True,
    )
    assert out["textureType"] == "Sprite (2D and UI)"
    assert out["filterMode"] == "Bilinear"
    assert out["wrapMode"] == "Clamp"
    assert out["mipmapEnabled"] is False
    assert out["alphaIsTransparency"] is True
    assert out["maxTextureSize"] == 512


def test_texture_pixel_art_small_image_gets_point():
    """A 64x64 image is automatically treated as pixel art → Point."""
    out = asset_import_script.decide_texture_import(
        "Assets/Sprites/Butcher_64.png", "Butcher 头像", 64, 64, has_alpha=True,
    )
    assert out["filterMode"] == "Point"


def test_texture_pixel_art_keyword_overrides_size():
    """Even a 512x512 image can be pixel art if detail says so."""
    out = asset_import_script.decide_texture_import(
        "Assets/Sprites/icon.png",
        "像素风游戏 icon, 512x512", 512, 512, has_alpha=True,
    )
    assert out["filterMode"] == "Point"


def test_texture_sprite_sheet_keyword():
    out = asset_import_script.decide_texture_import(
        "Assets/Sprites/Characters.png",
        "spritesheet，包含 5 个角色头像", 512, 512, has_alpha=True,
    )
    assert out["spriteMode"] == "Multiple"


def test_texture_normal_map_by_filename():
    out = asset_import_script.decide_texture_import(
        "Assets/Textures/brick_normal.png", "墙面贴图", 1024, 1024, has_alpha=False,
    )
    assert out["textureType"] == "NormalMap"


def test_texture_default_non_sprite():
    """No sprite keywords + not under /Sprites/ → Default texture."""
    out = asset_import_script.decide_texture_import(
        "Assets/Textures/wall.png", "墙壁纹理", 1024, 1024, has_alpha=False,
    )
    assert out["textureType"] == "Default"
    assert out["wrapMode"] == "Repeat"  # default textures repeat by default
    assert out["mipmapEnabled"] is True


def test_texture_alpha_flag_propagates():
    out_a = asset_import_script.decide_texture_import(
        "x.png", "sprite", 256, 256, has_alpha=True,
    )
    out_b = asset_import_script.decide_texture_import(
        "x.png", "sprite", 256, 256, has_alpha=False,
    )
    assert out_a["alphaIsTransparency"] is True
    assert out_b["alphaIsTransparency"] is False


def test_texture_max_size_power_of_2():
    """maxTextureSize must round up to a power of 2, capped at 4096."""
    out_1080 = asset_import_script.decide_texture_import(
        "x.png", "sprite", 1080, 1080, has_alpha=True,
    )
    assert out_1080["maxTextureSize"] == 2048  # 1080 → 2048
    out_5000 = asset_import_script.decide_texture_import(
        "x.png", "sprite", 5000, 5000, has_alpha=True,
    )
    assert out_5000["maxTextureSize"] == 4096  # capped


# ── Decision rules: 3D models ─────────────────────────────────────


def test_model_no_animation():
    out = asset_import_script.decide_model_import(
        "Assets/Models/Tree.fbx", "静态树木道具",
    )
    assert out["animationType"] == "None"


def test_model_with_animation_generic():
    out = asset_import_script.decide_model_import(
        "Assets/Models/Bird.fbx", "鸟类动画 + rig",
    )
    assert out["animationType"] == "Generic"


def test_model_humanoid():
    out = asset_import_script.decide_model_import(
        "Assets/Models/Hero.fbx", "主角 character 含 humanoid rig + 动画",
    )
    assert out["animationType"] == "Humanoid"


def test_model_normals_smooth_keyword():
    out = asset_import_script.decide_model_import(
        "Assets/Models/Stone.fbx", "smooth shading 石头",
    )
    assert out["importNormals"] == "Calculate"


# ── Decision rules: audio ─────────────────────────────────────────


def test_audio_short_sfx():
    out = asset_import_script.decide_audio_import(
        "Assets/Audio/SFX/jump.wav", "跳跃 sfx", duration_sec=0.5,
    )
    assert out["loadType"] == "DecompressOnLoad"
    assert out["compressionFormat"] == "ADPCM"
    assert out["forceToMono"] is True


def test_audio_long_bgm():
    out = asset_import_script.decide_audio_import(
        "Assets/Audio/BGM/title.wav", "BGM 标题音乐", duration_sec=120,
    )
    assert out["loadType"] == "Streaming"
    assert out["compressionFormat"] == "Vorbis"
    assert out["forceToMono"] is False


def test_audio_mid_range_voice():
    """5-30s clip with no SFX/BGM keywords → CompressedInMemory."""
    out = asset_import_script.decide_audio_import(
        "Assets/Audio/VO/intro_line.wav", "intro voiceover", duration_sec=10,
    )
    assert out["loadType"] == "CompressedInMemory"


def test_audio_bgm_keyword_overrides_short_duration():
    """If filename says 'bgm', treat as BGM even if duration is short."""
    out = asset_import_script.decide_audio_import(
        "Assets/Audio/bgm_loop.wav", "短循环 bgm", duration_sec=4,
    )
    assert out["loadType"] == "Streaming"


# ── _ceil_pow2 ────────────────────────────────────────────────────


@pytest.mark.parametrize("inp,expected", [
    (32, 32), (33, 64), (64, 64), (65, 128),
    (1080, 2048), (4097, 4096), (10000, 4096),
    (0, 32), (1, 32),  # floor at 32 (Unity's min)
])
def test_ceil_pow2(inp, expected):
    assert asset_import_script._ceil_pow2(inp) == expected


# ── File metadata readers ─────────────────────────────────────────


def test_read_image_meta_png(tmp_path):
    p = tmp_path / "x.png"
    Image.new("RGBA", (64, 32), (0, 0, 0, 128)).save(p, "PNG")
    w, h, alpha = asset_import_script._read_image_meta(p)
    assert (w, h) == (64, 32)
    assert alpha is True


def test_read_image_meta_jpeg_no_alpha(tmp_path):
    p = tmp_path / "x.jpg"
    Image.new("RGB", (100, 50), (255, 0, 0)).save(p, "JPEG")
    w, h, alpha = asset_import_script._read_image_meta(p)
    assert (w, h) == (100, 50)
    assert alpha is False


def test_read_image_meta_corrupt(tmp_path):
    p = tmp_path / "fake.png"
    p.write_text("not an image")
    w, h, alpha = asset_import_script._read_image_meta(p)
    assert (w, h, alpha) == (0, 0, False)  # graceful degradation


def test_read_audio_duration_wav(tmp_path):
    p = tmp_path / "x.wav"
    n_frames = 44100  # 1 second
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * n_frames)
    assert abs(asset_import_script._read_audio_duration(p) - 1.0) < 0.01


def test_read_audio_duration_non_wav_returns_zero(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"\xff\xfb")  # mp3 magic only
    # We don't decode mp3 in stdlib; duration comes back 0 and the
    # decision falls back to filename signals.
    assert asset_import_script._read_audio_duration(p) == 0.0


# ── Unity-project detection ───────────────────────────────────────


def test_is_unity_project_yes(tmp_path):
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "Assets").mkdir()
    assert asset_import_script._is_unity_project(str(tmp_path)) is True


def test_is_unity_project_no_project_settings(tmp_path):
    (tmp_path / "Assets").mkdir()
    assert asset_import_script._is_unity_project(str(tmp_path)) is False


def test_is_unity_project_empty_root_string():
    assert asset_import_script._is_unity_project("") is False


def test_is_unity_project_root_doesnt_exist():
    assert asset_import_script._is_unity_project("Z:/nonexistent") is False


# ── End-to-end with mocked Unity MCP ──────────────────────────────


@pytest.fixture
def env():
    return FakeCRUD()


@pytest.mark.asyncio
async def test_import_assets_for_task_skips_non_unity_root(tmp_path, env):
    """ComfyUI debug project (root = E:\\ComfyUIData, no ProjectSettings/)
    must not halt the Crew. Verdict='pass' with skip note."""
    env.seed("projects", [{"id": "p1", "root_path": str(tmp_path)}])
    env.seed("tasks", [{
        "id": "t1", "project_id": "p1",
        "title": "art", "detail": "",
        "output_paths": json.dumps(["Assets/Sprites/x.png"]),
    }])
    with patch("services.asset_import_script.crud", env):
        result = await asset_import_script.import_assets_for_task(
            task_id="t1", prev_payload=None,
            project_root=str(tmp_path),  # no ProjectSettings/
        )
    assert result["verdict"] == "pass"
    assert "not a Unity project" in result["summary"]
    assert result["imported"] == []


@pytest.mark.asyncio
async def test_import_assets_for_task_happy_path(tmp_path, env, monkeypatch):
    """End-to-end on a fake Unity project: 3 PNGs at different sizes,
    Unity MCP is mocked to return success."""
    # Build a fake Unity project structure
    (tmp_path / "ProjectSettings").mkdir()
    sprites = tmp_path / "Assets" / "Sprites"
    sprites.mkdir(parents=True)
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(sprites / "small.png", "PNG")
    Image.new("RGBA", (512, 512), (0, 0, 0, 0)).save(sprites / "medium.png", "PNG")
    Image.new("RGBA", (1080, 1080), (0, 0, 0, 0)).save(sprites / "large.png", "PNG")

    env.seed("projects", [{"id": "p1", "root_path": str(tmp_path)}])
    env.seed("tasks", [{
        "id": "t1", "project_id": "p1",
        "title": "art",
        "detail": "Butcher 头像 spritesheet, transparent background",
        "output_paths": json.dumps([
            "Assets/Sprites/small.png",
            "Assets/Sprites/medium.png",
            "Assets/Sprites/large.png",
        ]),
    }])

    # Mock the Unity MCP pool — record what each call asked for.
    mcp_calls: list[dict] = []

    class FakePool:
        def call(self, server_id: str, tool: str, args: dict) -> str:
            mcp_calls.append({"server": server_id, "tool": tool, "args": args})
            return "OK"

    def fake_get_pool():
        return FakePool()

    monkeypatch.setattr(
        "src.tools.builtin.unity._mcp.get_unity_mcp_pool", fake_get_pool,
        raising=False,
    )

    with patch("services.asset_import_script.crud", env):
        result = await asset_import_script.import_assets_for_task(
            task_id="t1", prev_payload=None,
            project_root=str(tmp_path),
        )

    assert result["verdict"] == "pass", result
    assert len(result["imported"]) == 3
    # All three got a `Sprite (2D and UI)` textureType (sprite keyword
    # + path under /Sprites/) — verifies the decision flow.
    for entry in result["imported"]:
        assert entry["settings"]["textureType"] == "Sprite (2D and UI)"
    # The 64x64 image got Point filter (pixel-art rule); the larger
    # ones got Bilinear.
    by_path = {e["path"]: e["settings"] for e in result["imported"]}
    assert by_path["Assets/Sprites/small.png"]["filterMode"] == "Point"
    assert by_path["Assets/Sprites/large.png"]["filterMode"] == "Bilinear"

    # Unity MCP saw 3 manage_asset modify + 1 refresh_unity at the end.
    modify_calls = [c for c in mcp_calls if c["tool"] == "manage_asset"]
    refresh_calls = [c for c in mcp_calls if c["tool"] == "refresh_unity"]
    assert len(modify_calls) == 3
    assert len(refresh_calls) == 1


@pytest.mark.asyncio
async def test_import_assets_for_task_path_escape_refused(tmp_path, env, monkeypatch):
    """A task with `output_paths=["../../etc/passwd"]` must be refused
    with a clear issue — never stat or modify anything outside root."""
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "Assets").mkdir()

    env.seed("projects", [{"id": "p1", "root_path": str(tmp_path)}])
    env.seed("tasks", [{
        "id": "t1", "project_id": "p1", "title": "evil", "detail": "",
        "output_paths": json.dumps(["../../../etc/passwd"]),
    }])

    class FakePool:
        def call(self, *a, **kw): raise AssertionError("must not call MCP for escape")

    monkeypatch.setattr(
        "src.tools.builtin.unity._mcp.get_unity_mcp_pool",
        lambda: FakePool(), raising=False,
    )

    with patch("services.asset_import_script.crud", env):
        result = await asset_import_script.import_assets_for_task(
            task_id="t1", prev_payload=None,
            project_root=str(tmp_path),
        )
    assert result["verdict"] == "fail"
    assert any("越过项目根目录" in i for i in result["issues"])


@pytest.mark.asyncio
async def test_import_assets_for_task_skips_missing_files(tmp_path, env, monkeypatch):
    """Files declared in output_paths but absent on disk → silently
    skipped (QA will catch them later). Doesn't fail the TA step."""
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "Assets").mkdir()

    env.seed("projects", [{"id": "p1", "root_path": str(tmp_path)}])
    env.seed("tasks", [{
        "id": "t1", "project_id": "p1", "title": "art", "detail": "",
        "output_paths": json.dumps(["Assets/Sprites/missing.png"]),
    }])

    class FakePool:
        called = False
        def call(self, *a, **kw): self.__class__.called = True; return "OK"

    monkeypatch.setattr(
        "src.tools.builtin.unity._mcp.get_unity_mcp_pool",
        lambda: FakePool(), raising=False,
    )

    with patch("services.asset_import_script.crud", env):
        result = await asset_import_script.import_assets_for_task(
            task_id="t1", prev_payload=None,
            project_root=str(tmp_path),
        )
    assert result["verdict"] == "pass"  # nothing to do, but not an error
    assert result["imported"] == []
    assert FakePool.called is False  # no MCP calls for missing files


@pytest.mark.asyncio
async def test_import_assets_for_task_mcp_error_surfaces(tmp_path, env, monkeypatch):
    """Unity MCP returns 'ERROR ...' → verdict=fail with the message."""
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "Assets" / "Sprites").mkdir(parents=True)
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(
        tmp_path / "Assets" / "Sprites" / "x.png", "PNG",
    )

    env.seed("projects", [{"id": "p1", "root_path": str(tmp_path)}])
    env.seed("tasks", [{
        "id": "t1", "project_id": "p1", "title": "art", "detail": "",
        "output_paths": json.dumps(["Assets/Sprites/x.png"]),
    }])

    class FailingPool:
        def call(self, *a, **kw):
            return "ERROR: Unity Editor not running"

    monkeypatch.setattr(
        "src.tools.builtin.unity._mcp.get_unity_mcp_pool",
        lambda: FailingPool(), raising=False,
    )

    with patch("services.asset_import_script.crud", env):
        result = await asset_import_script.import_assets_for_task(
            task_id="t1", prev_payload=None,
            project_root=str(tmp_path),
        )
    assert result["verdict"] == "fail"
    assert any("Unity MCP" in i for i in result["issues"])
