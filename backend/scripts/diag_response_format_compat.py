"""Probe whether configured providers support response_format for
structured-output enforcement (the B vs C decision in fruit-ninja
diagnosis).

Three modes are tested per provider:
  A. baseline      — no response_format (sanity check, must work)
  B. json_object   — `response_format={"type": "json_object"}` (legacy
                     OpenAI mode; loose "must be valid JSON" hint)
  C. json_schema   — `response_format={"type": "json_schema", ...}`
                     with a strict schema (modern OpenAI mode; the
                     enforcement Instructor / Pydantic-validator path
                     would lean on)

For each (provider, mode):
  - request: a single short prompt asking for a structured payload
  - record : status, raw response content, did it parse as JSON?, did
             it match the schema?

The goal is NOT "does the model produce the right answer". The goal is
"does the provider accept the parameter and at least try to follow it".
A 400 / "not supported" rules out that mode for that provider.

Run from backend/ with venv:
    backend/.venv/Scripts/python.exe scripts/diag_response_format_compat.py
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import traceback
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent

# (provider_db_name, litellm_prefix, model_name)
PROBES: list[tuple[str, str, str]] = [
    ("DeepSeek", "deepseek", "deepseek-v4-flash"),
    ("Qwen",     "dashscope", "qwen-plus"),
    ("GLM",      "openai",    "glm-4-plus"),     # GLM is OpenAI-compatible
    ("MiMo",     "openai",    "mimo-v2.5-pro"),
]

# Tiny schema — exactly what EmitOutputSpec might look like.
TARGET_SCHEMA = {
    "type": "object",
    "properties": {
        "file_paths": {
            "type": "array",
            "items": {"type": "string"},
        },
        "coverage": {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        },
    },
    "required": ["file_paths"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are a build assistant. Respond with a JSON object that lists "
    "the file paths you would create for a tiny Unity project that "
    "implements a fruit-ninja MouseSlicer.cs and FruitSpawner.cs."
)
USER = (
    "List 2 file paths under Assets/Scripts/ that you would create. "
    "Use the schema {file_paths: [string], coverage: {string: int}}."
)


def load_provider(name: str) -> tuple[str, str]:
    db = sqlite3.connect(str(ROOT / "data" / "db" / "mycrew.db"))
    db.row_factory = sqlite3.Row
    r = db.execute(
        "SELECT base_url, api_key_ref FROM llm_providers WHERE name=?", (name,),
    ).fetchone()
    db.close()
    if not r:
        return "", ""
    return r["base_url"], r["api_key_ref"]


def schema_check(d: dict) -> tuple[bool, str]:
    """Return (passes, reason)."""
    if not isinstance(d, dict):
        return False, "not a dict"
    fp = d.get("file_paths")
    if not isinstance(fp, list):
        return False, f"file_paths missing or wrong type ({type(fp).__name__})"
    if not all(isinstance(x, str) for x in fp):
        return False, "file_paths items not all strings"
    cov = d.get("coverage", {})
    if cov and not isinstance(cov, dict):
        return False, "coverage not dict"
    return True, "ok"


async def call_one(*, label: str, prefix: str, model: str,
                   base_url: str, api_key: str,
                   response_format) -> dict:
    """One LiteLLM call. response_format=None for baseline."""
    import litellm
    kwargs = dict(
        model=f"{prefix}/{model}",
        api_key=api_key,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER},
        ],
        temperature=0.2,
        max_tokens=400,
    )
    if base_url:
        kwargs["base_url"] = base_url
    if response_format is not None:
        kwargs["response_format"] = response_format

    out = {"label": label, "ok": False, "error": None,
           "content": "", "parse_ok": False, "schema_ok": False,
           "schema_reason": ""}
    try:
        resp = await litellm.acompletion(**kwargs)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        return out

    msg = resp.choices[0].message
    content = (getattr(msg, "content", None) or "").strip()
    out["content"] = content
    out["finish_reason"] = resp.choices[0].finish_reason

    # Sometimes content has markdown fence; strip.
    body = content
    if body.startswith("```"):
        nl = body.find("\n")
        if nl > 0:
            body = body[nl + 1:]
        if body.endswith("```"):
            body = body[:-3]
        body = body.strip()
    try:
        parsed = json.loads(body)
        out["parse_ok"] = True
        ok, reason = schema_check(parsed if isinstance(parsed, dict) else {})
        out["schema_ok"] = ok
        out["schema_reason"] = reason
    except (json.JSONDecodeError, TypeError) as exc:
        out["schema_reason"] = f"json parse failed: {exc}"

    out["ok"] = True
    return out


async def probe_provider(name: str, prefix: str, model: str) -> dict:
    base_url, api_key = load_provider(name)
    print(f"\n{'#' * 70}\n  {name}  /  {prefix}/{model}\n{'#' * 70}")
    if not api_key:
        print(f"  SKIP: no api_key for {name}")
        return {"name": name, "model": model, "skipped": True}

    results = {}
    for label, rf in [
        ("A_baseline",   None),
        ("B_json_object", {"type": "json_object"}),
        ("C_json_schema", {
            "type": "json_schema",
            "json_schema": {
                "name": "emit_output_payload",
                "schema": TARGET_SCHEMA,
                "strict": True,
            },
        }),
    ]:
        r = await call_one(
            label=label, prefix=prefix, model=model,
            base_url=base_url, api_key=api_key,
            response_format=rf,
        )
        results[label] = r
        if r["error"]:
            print(f"\n  [{label}]  ERROR  -> {r['error'][:200]}")
        else:
            print(f"\n  [{label}]  finish={r.get('finish_reason')}  "
                  f"parse_ok={r['parse_ok']}  schema_ok={r['schema_ok']} "
                  f"({r['schema_reason']})")
            print(f"      content[0:240]: {r['content'][:240]!r}")
    return {"name": name, "model": model, "results": results}


async def main() -> None:
    all_results = []
    for name, prefix, model in PROBES:
        r = await probe_provider(name, prefix, model)
        all_results.append(r)

    # ── Summary table ─────────────────────────────────────────────
    print(f"\n{'=' * 70}\n  SUMMARY\n{'=' * 70}")
    print(f"\n  {'provider':10} {'baseline':12} {'json_object':14} {'json_schema':14}")
    print("  " + "-" * 60)
    for r in all_results:
        if r.get("skipped"):
            print(f"  {r['name']:10} SKIPPED")
            continue
        rr = r["results"]
        def fmt(x):
            if x["error"]:
                return "ERR"
            mark = "✓" if x["parse_ok"] and x["schema_ok"] else (
                   "P" if x["parse_ok"] else "x"
            )
            return f"{mark} ({x['finish_reason'] or '?'})"
        print(f"  {r['name']:10} "
              f"{fmt(rr['A_baseline']):12} "
              f"{fmt(rr['B_json_object']):14} "
              f"{fmt(rr['C_json_schema']):14}")
    print("\n  Legend: ✓=parse+schema ok, P=parse ok schema fail, x=parse fail, ERR=400 / api error")

    out = ROOT / "data" / "diag_response_format_compat.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")
    print(f"\n  Full results: {out}")


if __name__ == "__main__":
    asyncio.run(main())
