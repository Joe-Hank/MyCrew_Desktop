"""Pure-function tests for services.metrics_svc.

Covers the cost-cents math and ISO timestamp diff — the two places where
silent wrong answers would propagate straight to the ProjectCard badges
(undercharging users, mis-reporting hours). DB-touching helpers
(record_llm_usage, task_run_*) are intentionally NOT covered here: they
live behind a global sqlite connection and the project's existing test
conventions (see test_inception_svc.py) keep that path out of the unit
suite.
"""
from datetime import datetime, timedelta, timezone

import pytest

from services.metrics_svc import (
    _elapsed_seconds,
    _parse_iso,
    compute_cost_cents,
)


# ── compute_cost_cents ────────────────────────────────────────────


def test_cost_is_zero_when_either_price_is_none():
    # The "user never set a price" state. We never want a partial charge
    # in this case — the badge would mislead more than help.
    assert compute_cost_cents(1000, 1000, None, 100) == 0
    assert compute_cost_cents(1000, 1000, 100, None) == 0
    assert compute_cost_cents(1000, 1000, None, None) == 0


def test_cost_typical_claude_sonnet_million():
    # 1M input @ ¥18/1M + 1M output @ ¥90/1M = ¥108 = 10_800 cents.
    assert compute_cost_cents(1_000_000, 1_000_000, 1800, 9000) == 10_800


def test_cost_small_call_rounds_down_to_zero():
    # Sub-million calls at sub-fen rates intentionally round to zero —
    # we'd rather under-bill than show "¥0.01" for a chat message
    # smaller than the price-per-million threshold.
    # 100 in * ¥0.5/M = 0.00005 fen → floor → 0.
    assert compute_cost_cents(100, 0, 50, 100) == 0
    # Boundary nudge: exactly 1 fen at the Claude rate (~556 input tokens).
    assert compute_cost_cents(1000, 0, 1800, 9000) == 1


def test_cost_clamps_negative_tokens_to_zero():
    # Adapter glitches occasionally surface -1 token counts; that
    # must not produce a negative cost (which would underflow the
    # project counter on aggregation).
    assert compute_cost_cents(-100, -100, 1800, 9000) == 0
    assert compute_cost_cents(1_000_000, -100, 1800, 9000) == 1800


def test_cost_deepseek_cheap_tier():
    # 5M tokens @ ¥0.5/1M each = ¥2.50+¥5.00 = ¥7.50 = 750 cents.
    assert compute_cost_cents(5_000_000, 5_000_000, 50, 100) == 750


def test_cost_zero_priced_model():
    # Explicit "0 / 0" means user disabled billing — keep costs at zero
    # regardless of token volume.
    assert compute_cost_cents(10_000_000, 10_000_000, 0, 0) == 0


# ── _parse_iso ────────────────────────────────────────────────────


def test_parse_iso_handles_z_suffix_and_offset():
    a = _parse_iso("2026-05-17T10:00:00Z")
    b = _parse_iso("2026-05-17T10:00:00+00:00")
    assert a == b
    assert a is not None and a.tzinfo is not None


def test_parse_iso_assumes_utc_for_naive():
    # Naive strings drift onto UTC so subtraction with a tz-aware
    # timestamp doesn't TypeError later on.
    a = _parse_iso("2026-05-17T10:00:00")
    assert a is not None
    assert a.tzinfo is timezone.utc


def test_parse_iso_returns_none_on_garbage():
    assert _parse_iso(None) is None
    assert _parse_iso("") is None
    assert _parse_iso("not a date") is None


# ── _elapsed_seconds ──────────────────────────────────────────────


def test_elapsed_typical_interval():
    start = "2026-05-17T10:00:00+00:00"
    end = "2026-05-17T10:01:30+00:00"
    assert _elapsed_seconds(start, end) == 90


def test_elapsed_clamps_negative_to_zero():
    # If the harness ever stamps a "started_at" newer than "finished_at"
    # (clock skew between machines, retry replaying), don't subtract from
    # the project's runtime — return 0 and let the bug be obvious in logs.
    later = "2026-05-17T10:01:00+00:00"
    earlier = "2026-05-17T10:00:00+00:00"
    assert _elapsed_seconds(later, earlier) == 0


def test_elapsed_unparseable_returns_zero():
    assert _elapsed_seconds(None, "2026-05-17T10:00:00Z") == 0
    assert _elapsed_seconds("garbage", "2026-05-17T10:00:00Z") == 0


def test_elapsed_floors_fractional_seconds():
    # Underlying delta carries microseconds; we keep whole seconds for
    # the SQL counter so two near-simultaneous transitions can't double-
    # count "0.999s" into a phantom 2 seconds via repeated round-up.
    start = "2026-05-17T10:00:00.000000+00:00"
    end = "2026-05-17T10:00:01.900000+00:00"
    assert _elapsed_seconds(start, end) == 1


# ── Symbolic compound: hour-long interval ──────────────────────────


def test_elapsed_hours():
    base = datetime(2026, 5, 17, 10, 0, 0, tzinfo=timezone.utc)
    end = base + timedelta(hours=3, minutes=7, seconds=42)
    assert _elapsed_seconds(base.isoformat(), end.isoformat()) == \
        3 * 3600 + 7 * 60 + 42
