"""Smoke test for synth_8bit_sfx: every recipe writes a valid 16-bit PCM
mono WAV under the bound project root.

Why pin the byte format: the QA agent in the Audio Crew verifies WAV
files exist + have a RIFF/WAVE header — a regression that wrote 32-bit
floats or empty placeholders would slip past file-existence but fail QA.
"""
from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from src.tools.builtin.local.synth_8bit_sfx import (
    SAMPLE_RATE,
    SFX_TYPES,
    make_synth_8bit_sfx_tool,
)


@pytest.mark.parametrize("sfx_type", SFX_TYPES)
def test_each_sfx_writes_valid_wav(tmp_path: Path, sfx_type: str):
    tool = make_synth_8bit_sfx_tool(str(tmp_path))
    result = tool._run(
        name=f"test_{sfx_type}",
        sfx_type=sfx_type,
        duration_ms=300,
        out_dir="Assets/Audio/SFX/",
    )
    assert "Wrote" in result, result

    out_path = tmp_path / "Assets" / "Audio" / "SFX" / f"test_{sfx_type}.wav"
    assert out_path.exists()
    assert out_path.stat().st_size > 44  # RIFF header is 44 bytes; payload must be >0

    with wave.open(str(out_path), "rb") as wf:
        assert wf.getnchannels() == 1, "must be mono"
        assert wf.getsampwidth() == 2, "must be 16-bit PCM"
        assert wf.getframerate() == SAMPLE_RATE
        assert wf.getnframes() > 1000


def test_riff_wave_header(tmp_path: Path):
    tool = make_synth_8bit_sfx_tool(str(tmp_path))
    tool._run(name="hdr", sfx_type="jump", duration_ms=100, out_dir=".")
    raw = (tmp_path / "hdr.wav").read_bytes()
    assert raw[:4] == b"RIFF"
    assert raw[8:12] == b"WAVE"
    # ChunkSize (raw[4:8]) should be file size minus 8
    chunk_size = struct.unpack("<I", raw[4:8])[0]
    assert chunk_size == len(raw) - 8


def test_path_escape_refused(tmp_path: Path):
    tool = make_synth_8bit_sfx_tool(str(tmp_path))
    # Try to write above the bound root
    result = tool._run(
        name="escape",
        sfx_type="jump",
        duration_ms=100,
        out_dir="../outside",
    )
    assert "[Error]" in result
    assert "escapes the project root" in result


def test_empty_name_rejected(tmp_path: Path):
    tool = make_synth_8bit_sfx_tool(str(tmp_path))
    result = tool._run(name="", sfx_type="jump", duration_ms=100, out_dir=".")
    assert "[Error]" in result


def test_extension_stripped(tmp_path: Path):
    tool = make_synth_8bit_sfx_tool(str(tmp_path))
    tool._run(name="jump.wav", sfx_type="jump", duration_ms=100, out_dir=".")
    # Should write jump.wav, not jump.wav.wav
    assert (tmp_path / "jump.wav").exists()
    assert not (tmp_path / "jump.wav.wav").exists()
