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
