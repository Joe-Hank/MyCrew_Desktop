"""LLM service — CRUD for providers/models + quota/availability checks."""
from __future__ import annotations

import json

import structlog

from infra.llm.gateway import llm_gateway
from infra.repo import crud

log = structlog.get_logger()

JSON_FIELDS: list[str] = []


class LlmService:
    async def list_providers(self) -> list[dict]:
        providers = await crud.get_all("llm_providers")
        for p in providers:
            p["models"] = await crud.get_all("llm_models", "provider_id = ?", (p["id"],))
            for m in p["models"]:
                m["supports_thinking"] = bool(m.get("supports_thinking", 0))
        return providers

    async def get_provider(self, provider_id: str) -> dict | None:
        p = await crud.get_by_id("llm_providers", provider_id)
        if p:
            p["models"] = await crud.get_all("llm_models", "provider_id = ?", (p["id"],))
            for m in p["models"]:
                m["supports_thinking"] = bool(m.get("supports_thinking", 0))
        return p

    async def create_provider(self, data: dict) -> dict:
        row = await crud.insert("llm_providers", {
            "name": data["name"],
            "type": data["type"],
            "api_key_ref": data.get("api_key_ref"),
            "base_url": data.get("base_url"),
        }, id_prefix="llm_")
        row["models"] = []
        log.info("llm.provider_created", id=row["id"])
        return row

    async def update_provider(self, provider_id: str, data: dict) -> dict | None:
        fields = {k: v for k, v in data.items() if v is not None and k != "id"}
        return await crud.update_by_id("llm_providers", provider_id, fields)

    async def delete_provider(self, provider_id: str) -> None:
        from infra.repo.sqlite_repo import get_db
        db = await get_db()
        await db.execute("DELETE FROM llm_models WHERE provider_id = ?", (provider_id,))
        await crud.delete_by_id("llm_providers", provider_id)
        log.info("llm.provider_deleted", id=provider_id)

    async def create_model(self, data: dict) -> dict:
        row = await crud.insert("llm_models", {
            "provider_id": data["provider_id"],
            "model_name": data["model_name"],
            "label": data.get("label"),
            "max_tokens": data.get("max_tokens"),
            "supports_thinking": 1 if data.get("supports_thinking") else 0,
        }, id_prefix="mdl_")
        row["supports_thinking"] = bool(row.get("supports_thinking", 0))
        log.info("llm.model_created", id=row["id"])
        return row

    async def update_model(self, model_id: str, data: dict) -> dict | None:
        fields = {k: v for k, v in data.items() if v is not None and k != "id"}
        if "supports_thinking" in fields:
            fields["supports_thinking"] = 1 if fields["supports_thinking"] else 0
        result = await crud.update_by_id("llm_models", model_id, fields)
        if result:
            result["supports_thinking"] = bool(result.get("supports_thinking", 0))
        return result

    async def delete_model(self, model_id: str) -> None:
        await crud.delete_by_id("llm_models", model_id)
        log.info("llm.model_deleted", id=model_id)

    # ── Thinking-mode capability probe ────────────────────────────
    #
    # The UI calls this when the user picks a model in the LLM editor
    # OR when an Agent's bound LLM changes — to decide whether the
    # 「思考模式」 toggle is interactive. The result is cached on
    # llm_models.supports_thinking so subsequent reads (and the
    # /llm/providers list) don't re-probe.
    #
    # The probe is currently a heuristic over the model_name string
    # because Anthropic / OpenAI both expose extended-thinking /
    # reasoning purely as a per-model capability (no API endpoint to
    # ask "does this support thinking?"). The heuristic err on the
    # side of false-negative — if the family is unknown, return false
    # so the toggle stays locked and we don't send a `thinking` field
    # the provider would reject.

    @staticmethod
    def _heuristic_supports_thinking(provider_type: str, model_name: str) -> bool:
        name = (model_name or "").lower()
        ptype = (provider_type or "").lower()

        if ptype == "anthropic":
            # Extended thinking is supported on Claude 3.7 Sonnet and
            # the Claude 4 family (Opus/Sonnet/Haiku 4.x). Anything
            # older (3.5 Sonnet, 3.5 Haiku, 3 Opus) is false.
            if "claude-3-7" in name or "claude-3.7" in name:
                return True
            if "claude-opus-4" in name or "claude-sonnet-4" in name:
                return True
            if "claude-haiku-4" in name:
                return True
            # Forward-compat: bare "claude-4-*" / "claude-5-*" patterns
            if name.startswith("claude-4-") or name.startswith("claude-5-"):
                return True
            return False

        if ptype == "openai":
            # OpenAI reasoning families: o1 / o3 / o4 / gpt-5 (which
            # routes reasoning models internally).
            if name.startswith("o1") or name.startswith("o3") or name.startswith("o4"):
                return True
            if name.startswith("gpt-5"):
                return True
            return False

        if ptype == "deepseek":
            # deepseek-reasoner exposes a `reasoning_content` field
            # similar to thinking. Plain chat/coder/flash variants do not.
            if "reasoner" in name or name.endswith("-r1"):
                return True
            return False

        if ptype == "qwen":
            # Qwen-3 / QwQ-32B reasoning variants. Plain qwen-turbo /
            # qwen-plus do not surface a thinking channel.
            if "qwq" in name or "reasoner" in name or "-thinking" in name:
                return True
            return False

        if ptype == "gemini":
            # Gemini 2.5 Pro / Flash with "thinking" suffix. Older
            # 1.5 / 2.0 do not.
            if "2.5" in name and "thinking" in name:
                return True
            return False

        # ollama / custom / unknown → cannot infer, default false.
        return False

    async def probe_thinking(
        self,
        *,
        model_id: str | None = None,
        provider_id: str | None = None,
        model_name: str | None = None,
    ) -> dict:
        """Probe (and cache) a model's thinking-mode capability.

        Accepts EITHER `model_id` (preferred — addresses the row directly)
        OR `provider_id` + `model_name` (when the model row hasn't been
        persisted yet, e.g. the user is typing a new model in the editor).

        Writes the result back into `llm_models.supports_thinking` when
        an existing row is found. Returns `{supports_thinking: bool,
        provider_type: str, model_name: str}`.
        """
        provider: dict | None = None
        model_row: dict | None = None
        resolved_name = model_name or ""

        if model_id:
            model_row = await crud.get_by_id("llm_models", model_id)
            if model_row:
                resolved_name = model_row["model_name"]
                provider = await crud.get_by_id(
                    "llm_providers", model_row["provider_id"]
                )
        elif provider_id and model_name:
            provider = await crud.get_by_id("llm_providers", provider_id)
            # Best-effort row lookup so we can still cache the result
            rows = await crud.get_all(
                "llm_models",
                "provider_id = ? AND model_name = ?",
                (provider_id, model_name),
            )
            model_row = rows[0] if rows else None

        if provider is None:
            return {
                "supports_thinking": False,
                "provider_type": "",
                "model_name": resolved_name,
                "cached": False,
            }

        supports = self._heuristic_supports_thinking(
            provider.get("type", ""), resolved_name
        )

        cached = False
        if model_row:
            await crud.update_by_id(
                "llm_models", model_row["id"],
                {"supports_thinking": 1 if supports else 0},
            )
            cached = True
            log.info(
                "llm.thinking_probe_cached",
                model_id=model_row["id"], supports=supports,
            )

        return {
            "supports_thinking": supports,
            "provider_type": provider.get("type", ""),
            "model_name": resolved_name,
            "cached": cached,
        }

    # 30s TTL cache (per plan §11.2 — quota probes are expensive)
    _quota_cache: list[dict] | None = None
    _quota_cache_at: float = 0.0
    _QUOTA_TTL = 30.0

    # Sticky-skip set (audit 2026-05-17): once a provider's probe
    # fails, we stop probing it on every cache miss. The user's log
    # was filling with the same two providers' 403 / 404 warnings
    # every 30s forever (Anthropic from CN; an old DashScope URL).
    # The probe stays skipped until the user clicks the home-page
    # "刷新" button, which calls get_quota(force=True) — that path
    # clears the set and re-probes fresh. If a provider fails again
    # on refresh it goes right back into the set.
    _unavailable_provider_ids: set[str] = set()

    @staticmethod
    def _stuck_status(provider: dict) -> dict:
        """Stub status returned for providers in the skip set so the
        UI still shows them (red dot) without re-probing the network."""
        return {
            "provider_id": provider["id"],
            "name": provider["name"],
            "type": provider["type"],
            "display": "unavailable",
            "value": None,
            "raw": "上次检测失败 — 主页「刷新」可重试",
        }

    async def get_quota(self, *, force: bool = False) -> list[dict]:
        """Per-provider quota status with three display modes (plan §11.2).

        Output items shape:
          {
            "provider_id": str, "name": str, "type": str,
            "display": "percent" | "tokens_m" | "available" | "unavailable",
            "value": int | None,   # for percent / tokens_m modes
            "raw": str | None,     # human-readable extra (e.g. "¥10.0")
          }

        Cached for 30s to avoid hammering provider endpoints. Pass
        force=True to bypass BOTH the cache AND the sticky-skip set —
        the only path that re-probes a previously-failed provider.
        """
        import time
        now = time.time()
        if (
            not force
            and self._quota_cache is not None
            and now - self._quota_cache_at < self._QUOTA_TTL
        ):
            return self._quota_cache

        # Force=True is the user clicking 刷新 — give every provider a
        # second chance (and any that fail again will repopulate the
        # skip set during the loop below).
        if force:
            if self._unavailable_provider_ids:
                log.info("llm.quota_skip_reset",
                         count=len(self._unavailable_provider_ids))
            self._unavailable_provider_ids = set()

        providers = await crud.get_all("llm_providers")
        results = []
        for p in providers:
            pid = p["id"]
            if pid in self._unavailable_provider_ids:
                # No network call — return the cached "stuck" stub.
                results.append(self._stuck_status(p))
                continue
            status = await self._probe_provider_quota(p)
            if status.get("display") == "unavailable":
                # First failure: mark for skip on the next cache miss.
                self._unavailable_provider_ids.add(pid)
                log.info("llm.quota_provider_marked_unavailable",
                         provider_id=pid, name=p["name"])
            results.append(status)

        self._quota_cache = results
        self._quota_cache_at = now

        # Broadcast so the frontend can patch its cache without waiting for
        # the next 30s tick (best-effort; manager may not be imported yet).
        try:
            from api.ws import manager
            await manager.broadcast("llm.quota_changed", {"providers": results})
        except Exception as exc:
            log.debug("llm.quota_broadcast_failed", error=str(exc))

        return results

    async def _probe_provider_quota(self, provider: dict) -> dict:
        """Probe a single provider, falling back to liveness check.

        Per-type dispatch:
          - deepseek → GET /user/balance, surfaces CNY balance as "tokens_m"
          - others   → liveness ping via llm_gateway.check_availability
        """
        base_status = {
            "provider_id": provider["id"],
            "name": provider["name"],
            "type": provider["type"],
            "display": "unavailable",
            "value": None,
            "raw": None,
        }

        ptype = (provider.get("type") or "").lower()
        try:
            if ptype == "deepseek":
                return await self._probe_deepseek(provider, base_status)
            # Future: add per-provider probes here.
            #   openai → /v1/dashboard/billing/credit_grants
            #   anthropic → /v1/organizations/usage  (if available)
            #   qwen/glm/mimo → liveness only for now

            # Generic fallback: just check the provider is reachable
            return await self._fallback_liveness(provider, base_status)
        except Exception as exc:
            log.warning("llm.quota_probe_failed",
                        provider_id=provider["id"],
                        error=str(exc))
            return base_status

    async def _probe_deepseek(self, provider: dict, status: dict) -> dict:
        """DeepSeek exposes /user/balance returning CNY balance.

        We map balance → 'tokens_m' (rough estimate, ~1 CNY ≈ 1M tokens
        on the cheap tier; this is just an indicator, not billing-accurate)."""
        import httpx

        base_url = (provider.get("base_url") or "").rstrip("/")
        if not base_url:
            base_url = "https://api.deepseek.com/v1"
        # /user/balance lives at the host root (no /v1 prefix on DeepSeek)
        host = base_url.split("/v1")[0].rstrip("/")
        url = f"{host}/user/balance"
        api_key = provider.get("api_key_ref") or ""

        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            r.raise_for_status()
            data = r.json()

        is_available = bool(data.get("is_available", False))
        infos = data.get("balance_infos") or []
        if infos:
            info = infos[0]
            balance_str = info.get("total_balance") or "0"
            try:
                balance = float(balance_str)
            except (ValueError, TypeError):
                balance = 0.0
            currency = info.get("currency", "CNY")
            # Plan §11.2: token count → integer M
            # Estimate: 1 CNY ≈ 1M tokens on DeepSeek discount tiers
            tokens_m_est = int(balance)
            status.update(
                display="tokens_m" if is_available else "unavailable",
                value=tokens_m_est,
                raw=f"{balance:.2f} {currency}",
            )
        else:
            status["display"] = "available" if is_available else "unavailable"
        return status

    async def _fallback_liveness(self, provider: dict, status: dict) -> dict:
        """Default for providers without a known quota endpoint."""
        available = await llm_gateway.check_availability(provider["id"])
        status["display"] = "available" if available else "unavailable"
        return status


llm_svc = LlmService()
