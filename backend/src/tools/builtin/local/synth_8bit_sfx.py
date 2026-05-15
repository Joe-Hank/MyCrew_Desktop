"""Synth8bitSfx — programmatic 8-bit-style WAV synthesizer.

Audio Crew's Executor 1 calls this tool to materialize each .wav file the
PM contract demands. Why programmatic instead of an audio-generation model:
  - Free + offline (no API quota)
  - Deterministic — the same args produce the same file, important for
    QA's path-existence check
  - 8-bit retro is plenty for the games PM v4 targets (Pac-Man-class
    pixel-art projects)

Each sfx_type maps to a hand-tuned recipe (oscillator type, frequency
sweep, ADSR envelope, noise mix). Output is 16-bit PCM mono WAV at
44.1 kHz, written under the project root with workspace-style escape
guard. Future swap to AudioCraft / MusicGen lives behind the same
signature.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import ClassVar, Literal

import numpy as np
import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool
from src.tools.builtin.local.workspace import _resolve_in_root

log = structlog.get_logger()


SAMPLE_RATE = 44100
SFX_TYPES = (
    "jump", "hit", "pickup", "explosion",
    "shoot", "footstep", "victory", "death",
)


# ── Envelope + oscillator helpers ──────────────────────────────────

def _adsr(n_samples: int, attack: float, decay: float, sustain: float, release: float) -> np.ndarray:
    """Linear ADSR envelope spanning n_samples. Fractions sum to <= 1.0."""
    a = max(1, int(n_samples * attack))
    d = max(1, int(n_samples * decay))
    r = max(1, int(n_samples * release))
    s = max(0, n_samples - a - d - r)
    env = np.concatenate([
        np.linspace(0.0, 1.0, a, dtype=np.float32),
        np.linspace(1.0, sustain, d, dtype=np.float32),
        np.full(s, sustain, dtype=np.float32),
        np.linspace(sustain, 0.0, r, dtype=np.float32),
    ])
    # Trim/pad to exact length
    if len(env) > n_samples:
        env = env[:n_samples]
    elif len(env) < n_samples:
        env = np.pad(env, (0, n_samples - len(env)))
    return env


def _square_sweep(n_samples: int, f_start: float, f_end: float) -> np.ndarray:
    """Square wave with linear frequency sweep — the 8-bit staple."""
    t = np.arange(n_samples, dtype=np.float32) / SAMPLE_RATE
    freqs = np.linspace(f_start, f_end, n_samples, dtype=np.float32)
    phase = np.cumsum(2.0 * math.pi * freqs / SAMPLE_RATE)
    return np.sign(np.sin(phase)).astype(np.float32)


def _triangle(n_samples: int, freq: float) -> np.ndarray:
    t = np.arange(n_samples, dtype=np.float32) / SAMPLE_RATE
    return (2.0 / math.pi) * np.arcsin(np.sin(2.0 * math.pi * freq * t)).astype(np.float32)


def _noise(n_samples: int) -> np.ndarray:
    return np.random.uniform(-1.0, 1.0, n_samples).astype(np.float32)


# ── Recipes per sfx_type ───────────────────────────────────────────

def _render_sfx(sfx_type: str, duration_ms: int) -> np.ndarray:
    """Return float32 mono samples in [-1, 1] for the requested sfx."""
    n = max(int(SAMPLE_RATE * duration_ms / 1000), 100)
    if sfx_type == "jump":
        # Rising square sweep, short and bright
        wave_ = _square_sweep(n, 220.0, 880.0)
        env = _adsr(n, 0.02, 0.10, 0.7, 0.20)
    elif sfx_type == "hit":
        # Square punch + noise burst, downward
        wave_ = 0.7 * _square_sweep(n, 440.0, 110.0) + 0.4 * _noise(n)
        env = _adsr(n, 0.005, 0.05, 0.4, 0.30)
    elif sfx_type == "pickup":
        # Two-tone ascending blip — coin-style
        half = n // 2
        a = _triangle(half, 660.0)
        b = _triangle(n - half, 990.0)
        wave_ = np.concatenate([a, b])
        env = _adsr(n, 0.01, 0.05, 0.8, 0.25)
    elif sfx_type == "explosion":
        # Noise-heavy descending sweep
        wave_ = 0.3 * _square_sweep(n, 200.0, 60.0) + 0.9 * _noise(n)
        env = _adsr(n, 0.01, 0.20, 0.5, 0.40)
    elif sfx_type == "shoot":
        # Fast downward sweep + short noise
        wave_ = 0.8 * _square_sweep(n, 1200.0, 200.0) + 0.3 * _noise(n)
        env = _adsr(n, 0.005, 0.10, 0.3, 0.20)
    elif sfx_type == "footstep":
        # Low thud — short noise burst
        wave_ = 0.2 * _triangle(n, 80.0) + 0.6 * _noise(n)
        env = _adsr(n, 0.01, 0.05, 0.2, 0.10)
    elif sfx_type == "victory":
        # Three-tone arpeggio (C-E-G-ish)
        third = n // 3
        rest = n - 2 * third
        a = _triangle(third, 523.0)   # C5
        b = _triangle(third, 659.0)   # E5
        c = _triangle(rest, 784.0)    # G5
        wave_ = np.concatenate([a, b, c])
        env = _adsr(n, 0.02, 0.10, 0.85, 0.30)
    elif sfx_type == "death":
        # Long descending square sweep
        wave_ = _square_sweep(n, 440.0, 55.0)
        env = _adsr(n, 0.05, 0.20, 0.6, 0.50)
    else:
        # Fallback: short blip
        wave_ = _triangle(n, 440.0)
        env = _adsr(n, 0.05, 0.20, 0.6, 0.30)

    samples = wave_ * env
    # Soft clip + leave a small headroom so int16 conversion never wraps
    samples = np.tanh(samples * 0.9) * 0.85
    return samples.astype(np.float32)


def _write_wav(path: Path, samples: np.ndarray) -> int:
    """Write float32 [-1,1] samples as 16-bit PCM mono WAV. Returns bytes."""
    int_samples = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
    raw = int_samples.tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(raw)
    return path.stat().st_size


# ── Tool wiring ────────────────────────────────────────────────────

class Synth8bitSfxArgs(BaseModel):
    name: str = Field(
        ...,
        description="File stem (no extension). e.g. 'jump_01' → writes 'jump_01.wav'.",
    )
    sfx_type: Literal[
        "jump", "hit", "pickup", "explosion",
        "shoot", "footstep", "victory", "death",
    ] = Field(
        ...,
        description="Recipe to synthesize. Pick the one closest to the desired sound.",
    )
    duration_ms: int = Field(
        500,
        ge=50,
        le=5000,
        description="Sound length in milliseconds (50–5000).",
    )
    out_dir: str = Field(
        ...,
        description=(
            "Output directory inside the project workspace (relative "
            "preferred, e.g. 'Assets/Audio/SFX/'). Created if missing."
        ),
    )


class Synth8bitSfx(GuardedLocalTool):
    name: str = "synth_8bit_sfx"
    description: str = (
        "Synthesize an 8-bit-style sound effect to a WAV file. Pure "
        "Python (numpy + wave) — no LLM, no API. Use this to materialize "
        "every SFX path the task's output_paths declares. Returns the "
        "absolute and project-relative paths plus byte size."
    )
    args_schema: type[BaseModel] = Synth8bitSfxArgs
    permission_kind: ClassVar[str | None] = "file_write"

    _bound_root: ClassVar[str] = ""

    def _run(self, name: str, sfx_type: str, duration_ms: int, out_dir: str) -> str:
        resolved_dir = _resolve_in_root(self._bound_root, out_dir)
        if isinstance(resolved_dir, str):
            return resolved_dir

        # Strip any extension the LLM accidentally added, then enforce .wav
        clean_name = Path(name).stem
        if not clean_name:
            return "[Error] name must not be empty."

        async def _do() -> str:
            try:
                resolved_dir.mkdir(parents=True, exist_ok=True)
                out_path = resolved_dir / f"{clean_name}.wav"
                samples = _render_sfx(sfx_type, duration_ms)
                size = _write_wav(out_path, samples)
                rel = out_path.relative_to(Path(self._bound_root))
                log.info("synth_8bit_sfx.ok",
                         path=str(out_path), bytes=size,
                         sfx_type=sfx_type, duration_ms=duration_ms)
                return (
                    f"Wrote {size} bytes to {rel} "
                    f"({sfx_type}, {duration_ms}ms, 44.1kHz 16-bit mono PCM)."
                )
            except Exception as exc:
                return f"[Error] synth_8bit_sfx failed: {exc}"

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            return f"[Error] synth_8bit_sfx failed: {exc}"


def make_synth_8bit_sfx_tool(project_root: str | None) -> Synth8bitSfx:
    """Factory: bind a project_root for workspace-scoped writes."""
    root = project_root or ""

    class _Bound(Synth8bitSfx):
        _bound_root: ClassVar[str] = root

    return _Bound()


__all__ = [
    "Synth8bitSfx",
    "make_synth_8bit_sfx_tool",
    "SFX_TYPES",
    "SAMPLE_RATE",
]
