"""Inception service — manages project inception sessions, LLM calls, blueprint parsing."""
from __future__ import annotations

import json

import structlog

from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud
from api.ws import manager

log = structlog.get_logger()

SYSTEM_PROMPT = """你是 MyCrew 项目立项助手。用户会描述他们的想法，你需要帮他们拆解成可执行的任务。

你的输出必须在最终回复中包含一个 ```json 代码块，格式如下：
{
  "name": "项目名称",
  "execution_kind": "sequential" | "crew" | "flow",
  "tasks": [
    {
      "title": "任务标题",
      "detail": "详细描述",
      "deps": [],
      "output_schema": {},
      "kind": "regular"
    }
  ]
}

规则：
- 1~2 个任务用 sequential，3~5 个用 crew，6+ 个用 flow
- 每个任务必须有 output_schema（JSON Schema 格式，可以为 {} 表示自由文本）
- 最后一个任务必须是 kind="final_qa"，用于总质检
- deps 是前置任务的索引列表（0-based）
- output_schema 应该是合法的 JSON Schema，描述该任务的输出结构
- final_qa 的 output_schema 必须包含 verdict(pass/warn/fail)、overall_score(number)、issues(array)、summary(string)
"""


class InceptionService:
    async def create_session(self, llm_id: str,
                              thinking_mode: bool = False) -> dict:
        session = await crud.insert("inception_sessions", {
            "llm_id": llm_id,
            "thinking_mode": 1 if thinking_mode else 0,
            "system_prompt": SYSTEM_PROMPT,
            "indexed_paths": "[]",
        }, id_prefix="incep_")
        log.info("inception.session_created", id=session["id"])
        return session

    async def list_sessions(self) -> list[dict]:
        rows = await crud.get_all("inception_sessions")
        result = []
        for r in rows:
            session = dict(r)
            if session.get("project_id"):
                project = await crud.get_by_id("projects", session["project_id"])
                session["project_name"] = project["name"] if project else None
            else:
                session["project_name"] = None
            session["is_draft"] = session.get("project_id") is None
            result.append(session)
        return result

    async def get_session(self, session_id: str) -> dict | None:
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            return None
        messages = await crud.get_all("inception_messages",
                                       "session_id = ?", (session_id,))
        result = dict(session)
        result["messages"] = [dict(m) for m in messages]
        return result

    async def send_message(self, session_id: str, content: str) -> dict:
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            raise KeyError(f"Session {session_id} not found")

        user_msg = await crud.insert("inception_messages", {
            "session_id": session_id,
            "role": "user",
            "content": content,
        }, id_prefix="msg_")

        await manager.broadcast("inception.message", {
            "session_id": session_id,
            "role": "user",
            "content": content,
        })

        ai_response = await self._call_llm(session_id, session, content)

        ai_msg = await crud.insert("inception_messages", {
            "session_id": session_id,
            "role": "assistant",
            "content": ai_response,
        }, id_prefix="msg_")

        await manager.broadcast("inception.message", {
            "session_id": session_id,
            "role": "assistant",
            "content": ai_response,
        })

        blueprint = self._try_parse_blueprint(ai_response)
        if blueprint:
            await manager.broadcast("inception.tasks_drafted", {
                "session_id": session_id,
                "blueprint": blueprint,
            })

        return {
            "user_message": dict(user_msg),
            "ai_message": dict(ai_msg),
            "blueprint": blueprint,
        }

    async def stream_message(self, session_id: str, content: str):
        """Stream version of send_message — yields deltas via WS."""
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            raise KeyError(f"Session {session_id} not found")

        await crud.insert("inception_messages", {
            "session_id": session_id,
            "role": "user",
            "content": content,
        }, id_prefix="msg_")

        await manager.broadcast("inception.message", {
            "session_id": session_id,
            "role": "user",
            "content": content,
        })

        # Build conversation history
        messages = await self._build_messages(session_id, session)

        # Resolve LLM config
        llm_id = session.get("llm_id", "")
        provider_id, model_name = await self._resolve_llm(llm_id)
        thinking_mode = bool(session.get("thinking_mode", 0))

        # Stream response
        full_text = ""
        async for delta in llm_gateway.stream(
            provider_id, model_name, messages,
            thinking_mode=thinking_mode,
        ):
            if delta.text:
                full_text += delta.text
                await manager.broadcast("inception.delta", {
                    "session_id": session_id,
                    "text": delta.text,
                })

        # Save complete AI message
        await crud.insert("inception_messages", {
            "session_id": session_id,
            "role": "assistant",
            "content": full_text,
        }, id_prefix="msg_")

        await manager.broadcast("inception.message", {
            "session_id": session_id,
            "role": "assistant",
            "content": full_text,
        })

        # Check for blueprint
        blueprint = self._try_parse_blueprint(full_text)
        if blueprint:
            await manager.broadcast("inception.tasks_drafted", {
                "session_id": session_id,
                "blueprint": blueprint,
            })

        return {"ai_text": full_text, "blueprint": blueprint}

    async def index_path(self, session_id: str, path: str) -> dict:
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            raise KeyError(f"Session {session_id} not found")

        indexed = session.get("indexed_paths", "[]")
        if isinstance(indexed, str):
            try:
                indexed = json.loads(indexed)
            except (json.JSONDecodeError, TypeError):
                indexed = []

        if path not in indexed:
            indexed.append(path)
            await crud.update_by_id("inception_sessions", session_id, {
                "indexed_paths": json.dumps(indexed),
            })

        return {"indexed_paths": indexed}

    async def finalize(self, session_id: str, blueprint: dict | None = None) -> dict:
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            raise KeyError(f"Session {session_id} not found")

        if not blueprint:
            messages = await crud.get_all("inception_messages",
                                           "session_id = ?", (session_id,))
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    blueprint = self._try_parse_blueprint(msg["content"])
                    if blueprint:
                        break

        if not blueprint or not blueprint.get("tasks"):
            raise ValueError("No valid task blueprint found")

        # Ensure final_qa task exists
        tasks = blueprint["tasks"]
        has_final_qa = any(t.get("kind") == "final_qa" for t in tasks)
        if not has_final_qa:
            tasks.append({
                "title": "质量检查",
                "detail": "对整个项目进行最终质量审查",
                "deps": [i for i in range(len(tasks))
                         if not any(i in t.get("deps", []) for t in tasks)],
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": ["pass", "warn", "fail"]},
                        "overall_score": {"type": "number"},
                        "issues": {"type": "array", "items": {"type": "object"}},
                        "summary": {"type": "string"},
                    },
                    "required": ["verdict", "overall_score", "issues", "summary"],
                },
                "kind": "final_qa",
            })

        from services.project_svc import project_svc

        task_data = []
        for i, t in enumerate(tasks):
            task_data.append({
                "title": t["title"],
                "detail": t.get("detail", ""),
                "kind": t.get("kind", "regular"),
                "output_schema": t.get("output_schema", {}),
                "deps": t.get("deps", []),
            })

        project = await project_svc.create_project_with_tasks(
            data={
                "name": blueprint.get("name", f"项目-{session_id[-6:]}"),
                "execution_kind": blueprint.get("execution_kind", "sequential"),
            },
            tasks=task_data,
        )

        await crud.update_by_id("inception_sessions", session_id, {
            "project_id": project["id"],
        })

        await manager.broadcast("inception.finalized", {
            "session_id": session_id,
            "project_id": project["id"],
        })

        log.info("inception.finalized",
                 session_id=session_id, project_id=project["id"])
        return project

    # ── LLM integration ────────────────────────────────────

    async def _call_llm(self, session_id: str, session: dict,
                         user_content: str) -> str:
        """Call LLM with full conversation history."""
        messages = await self._build_messages(session_id, session)

        llm_id = session.get("llm_id", "")
        provider_id, model_name = await self._resolve_llm(llm_id)
        thinking_mode = bool(session.get("thinking_mode", 0))

        try:
            response = await llm_gateway.chat(
                provider_id, model_name, messages,
                thinking_mode=thinking_mode,
            )
            log.info("inception.llm_called",
                     session_id=session_id,
                     tokens=response.usage.total_tokens,
                     model=response.model)
            return response.text
        except Exception as exc:
            log.error("inception.llm_error",
                      session_id=session_id, error=str(exc))
            raise ValueError(f"LLM 调用失败: {exc}") from exc

    async def _build_messages(self, session_id: str,
                               session: dict) -> list[LlmMessage]:
        """Build the full message list for LLM call."""
        messages: list[LlmMessage] = []

        # System prompt
        system_prompt = session.get("system_prompt", SYSTEM_PROMPT)
        messages.append(LlmMessage(role="system", content=system_prompt))

        # Add indexed paths context if any
        indexed = session.get("indexed_paths", "[]")
        if isinstance(indexed, str):
            try:
                indexed = json.loads(indexed)
            except (json.JSONDecodeError, TypeError):
                indexed = []
        if indexed:
            context = "用户已索引以下文件/目录供参考：\n" + "\n".join(f"- {p}" for p in indexed)
            messages.append(LlmMessage(role="system", content=context))

        # Conversation history
        history = await crud.get_all("inception_messages",
                                      "session_id = ?", (session_id,))
        for msg in history:
            role = msg["role"]
            if role in ("user", "assistant"):
                messages.append(LlmMessage(role=role, content=msg["content"]))

        return messages

    async def _resolve_llm(self, llm_id: str) -> tuple[str, str]:
        """Resolve llm_id to (provider_id, model_name).

        llm_id format: "provider_id:model_name" or just "provider_id"
        (in which case we use the first model).
        Falls back to default_inception_model from app_settings.
        """
        if not llm_id:
            llm_id = await self._get_default_inception_llm()

        if ":" in llm_id:
            parts = llm_id.split(":", 1)
            return parts[0], parts[1]

        # llm_id is just provider_id, get first model
        models = await crud.get_all("llm_models", "provider_id = ?", (llm_id,))
        if models:
            return llm_id, models[0]["model_name"]

        raise ValueError(f"无法解析 LLM 配置: {llm_id}，请先在设置页配置 LLM")

    async def _get_default_inception_llm(self) -> str:
        """Get default inception LLM from app_settings."""
        row = await crud.get_all("app_settings", "key = ?", ("default_inception_model",))
        if row:
            return row[0].get("value", "")

        # Fallback: use any available provider
        providers = await crud.get_all("llm_providers")
        if providers:
            provider = providers[0]
            models = await crud.get_all("llm_models",
                                         "provider_id = ?", (provider["id"],))
            if models:
                return f"{provider['id']}:{models[0]['model_name']}"

        raise ValueError("未配置任何 LLM，请先在设置页添加 LLM 配置")

    # ── Blueprint parsing ──────────────────────────────────

    def _try_parse_blueprint(self, text: str) -> dict | None:
        import re
        match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "tasks" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return None


inception_svc = InceptionService()
