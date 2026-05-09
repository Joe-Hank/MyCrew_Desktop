"""Inception service — manages project inception sessions, LLM calls, blueprint parsing."""
from __future__ import annotations

import json

import structlog

from infra.repo import crud
from api.ws import manager

log = structlog.get_logger()

SYSTEM_PROMPT = """你是 MyCrew 项目立项助手。用户会描述他们的想法，你需要帮他们拆解成可执行的任务。

你的输出必须在最终回复中包含一个 ```json 代码块，格式如下：
{
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
- 每个任务必须有 output_schema（可以为 {} 表示自由文本）
- 最后一个任务必须是 kind="final_qa"，用于总质检
- deps 是前置任务的索引列表（0-based）
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

        from services.project_svc import project_svc

        tasks = blueprint["tasks"]
        task_data = []
        for i, t in enumerate(tasks):
            deps_indices = t.get("deps", [])
            task_data.append({
                "title": t["title"],
                "detail": t.get("detail", ""),
                "kind": t.get("kind", "regular"),
                "output_schema": t.get("output_schema", {}),
                "deps": [],
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

    async def _call_llm(self, session_id: str, session: dict,
                         user_content: str) -> str:
        # Phase 5b+ will wire actual LLM API calls.
        # For now, return a mock response with a valid blueprint.
        return (
            "好的，我来帮你拆解这个项目。\n\n"
            "```json\n"
            "{\n"
            '  "name": "' + user_content[:20] + '",\n'
            '  "execution_kind": "sequential",\n'
            '  "tasks": [\n'
            '    {\n'
            '      "title": "需求分析",\n'
            '      "detail": "分析用户需求，明确功能范围",\n'
            '      "deps": [],\n'
            '      "output_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},\n'
            '      "kind": "regular"\n'
            '    },\n'
            '    {\n'
            '      "title": "实施执行",\n'
            '      "detail": "根据需求分析结果执行实施",\n'
            '      "deps": [0],\n'
            '      "output_schema": {"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},\n'
            '      "kind": "regular"\n'
            '    },\n'
            '    {\n'
            '      "title": "质量检查",\n'
            '      "detail": "对整个项目进行最终质量审查",\n'
            '      "deps": [1],\n'
            '      "output_schema": {"type": "object", "properties": {"verdict": {"type": "string"}, "score": {"type": "number"}}, "required": ["verdict", "score"]},\n'
            '      "kind": "final_qa"\n'
            '    }\n'
            '  ]\n'
            "}\n"
            "```\n"
        )

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
