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
        """Send a user message and run Plan Maker (CrewAI) to respond.

        Behaviour:
          1. Persist user message + broadcast inception.message.
          2. If a Plan Maker agent exists, run it via CrewAI with the
             create_workflow tool bound to this session_id. Stream coarse
             per-step deltas via inception.delta.
          3. If Plan Maker is missing (fresh DB, etc.), fall back to the
             legacy direct-LLM streaming path.
        """
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            raise KeyError(f"Session {session_id} not found")

        # 1. Persist + broadcast user message
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

        # 2. Plan Maker path (preferred)
        plan_maker = await self._get_plan_maker_agent()
        if plan_maker is not None:
            return await self._run_plan_maker(session_id, session, content, plan_maker)

        # 3. Legacy fallback — direct LLM streaming
        log.warning("inception.plan_maker_missing_using_legacy",
                    session_id=session_id)
        return await self._legacy_stream(session_id, session)

    async def _legacy_stream(self, session_id: str, session: dict) -> dict:
        """Old direct-LLM streaming path. Used only when Plan Maker is absent.

        The user message is already persisted by the caller; this path
        re-reads it from the messages table via _build_messages.
        """
        messages = await self._build_messages(session_id, session)
        llm_id = session.get("llm_id", "")
        provider_id, model_name = await self._resolve_llm(llm_id)
        thinking_mode = bool(session.get("thinking_mode", 0))

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

        blueprint = self._try_parse_blueprint(full_text)
        if blueprint:
            await manager.broadcast("inception.tasks_drafted", {
                "session_id": session_id,
                "blueprint": blueprint,
            })

        return {"ai_text": full_text, "blueprint": blueprint}

    async def _run_plan_maker(
        self,
        session_id: str,
        session: dict,
        content: str,
        plan_maker: dict,
    ) -> dict:
        """Run the Plan Maker CrewAI agent. Emits inception.delta per step
        and lets the create_workflow tool emit inception.workflow_created."""
        import asyncio
        from crewai import Agent, Crew, Process, Task
        from services.crewai_runner import _build_crewai_llm
        from src.tools.builtin.local.create_workflow import make_create_workflow_tool
        from bootstrap.seed_plan_maker import render_plan_maker_backstory

        # Resolve LLM: prefer agent's bound LLM, fall back to session's
        llm_id_source = plan_maker.get("llm_id") or session.get("llm_id", "")
        provider_id, model_name = await self._resolve_llm(llm_id_source)
        provider = await crud.get_by_id("llm_providers", provider_id)
        if not provider:
            raise ValueError(f"LLM provider {provider_id} not found")

        llm = _build_crewai_llm(provider, model_name)

        # Render placeholders in backstory with current MCP + agent inventory
        rendered_backstory = await render_plan_maker_backstory(
            plan_maker.get("backstory", "")
        )

        # Compose task description: history + new user input
        history = await self._format_history_for_task(session_id)
        description = (
            f"## 当前会话 ID\n{session_id}\n\n"
            f"## 对话历史\n{history}\n\n"
            f"## 用户最新输入\n{content}\n\n"
            "请：(1) 用自然语言回复用户；(2) 当方案明确时调用 create_workflow 工具持久化。"
        )

        agent = Agent(
            role=plan_maker.get("role", "Plan Maker"),
            goal=plan_maker.get("goal", ""),
            backstory=rendered_backstory,
            llm=llm,
            tools=[make_create_workflow_tool(session_id)],
            max_iter=int(plan_maker.get("max_retry") or 5),
            verbose=False,
            allow_delegation=False,
        )
        task = Task(
            description=description,
            expected_output="自然语言回复 + (当方案成熟时) 一次 create_workflow 工具调用。",
            agent=agent,
        )

        # Capture main loop so step_callback (which runs on worker thread)
        # can hop back here to broadcast WS deltas.
        main_loop = asyncio.get_running_loop()

        def _step_cb(step: object) -> None:
            text = self._extract_text_from_step(step)
            if not text:
                return
            try:
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast("inception.delta", {
                        "session_id": session_id,
                        "text": text,
                    }),
                    main_loop,
                )
            except Exception as exc:  # never let callback errors crash kickoff
                log.warning("inception.step_broadcast_failed", error=str(exc))

        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
            memory=False,
            step_callback=_step_cb,
        )

        try:
            result = await asyncio.to_thread(crew.kickoff)
        except Exception as exc:
            log.error("inception.crewai_kickoff_failed",
                      session_id=session_id, error=str(exc))
            raise ValueError(f"Plan Maker 调用失败: {exc}") from exc

        full_text = str(getattr(result, "raw", result) or "").strip()

        # Persist assistant message + broadcast final message event
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

        # Fallback: if Plan Maker emitted a JSON block instead of calling
        # the tool, try to salvage it as a draft (no DB persistence — UI
        # treats this as legacy preview).
        bound = await crud.get_by_id("inception_sessions", session_id)
        if bound and not bound.get("project_id"):
            salvaged = self._try_parse_blueprint(full_text)
            if salvaged:
                log.info("inception.salvaged_blueprint_from_text",
                         session_id=session_id)
                await manager.broadcast("inception.tasks_drafted", {
                    "session_id": session_id,
                    "blueprint": salvaged,
                })

        return {
            "ai_text": full_text,
            "project_id": bound.get("project_id") if bound else None,
        }

    # ── Plan Maker helpers ─────────────────────────────────────

    async def _get_plan_maker_agent(self) -> dict | None:
        rows = await crud.get_all("agents", "role = ?", ("Plan Maker",))
        return rows[0] if rows else None

    async def _format_history_for_task(self, session_id: str) -> str:
        """Flatten message history to a compact transcript for the task description."""
        rows = await crud.get_all(
            "inception_messages", "session_id = ?", (session_id,)
        )
        if not rows:
            return "（无历史）"
        lines = []
        # Keep only the last ~20 messages to stay within reasonable token budget
        for m in rows[-20:]:
            role = "用户" if m.get("role") == "user" else "Plan Maker"
            content = (m.get("content") or "").strip()
            if content:
                lines.append(f"[{role}] {content}")
        return "\n".join(lines) or "（无历史）"

    @staticmethod
    def _extract_text_from_step(step: object) -> str:
        """Best-effort extraction of human-readable text from a CrewAI step.

        CrewAI passes AgentAction / AgentFinish / ToolResult objects to
        step_callback; their shapes vary across versions, so we probe
        common attributes and stringify defensively.
        """
        try:
            # AgentFinish typically has .output or .return_values["output"]
            output = getattr(step, "output", None)
            if isinstance(output, str) and output.strip():
                return output.strip()[:500]
            rv = getattr(step, "return_values", None)
            if isinstance(rv, dict) and rv.get("output"):
                return str(rv["output"])[:500]
            # AgentAction has .tool and .tool_input
            tool = getattr(step, "tool", None)
            tool_input = getattr(step, "tool_input", None)
            if tool:
                summary = f"⚙️ 调用工具 {tool}"
                if tool_input:
                    summary += f"({str(tool_input)[:120]}...)"
                return summary
            # Fallback: stringify
            s = str(step)[:300]
            return s if s and s != "None" else ""
        except Exception:
            return ""

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
