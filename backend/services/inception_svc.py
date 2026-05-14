"""Inception service — manages project inception sessions, LLM calls, blueprint parsing."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict

import structlog

from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud
from api.ws import manager

log = structlog.get_logger()

SYSTEM_PROMPT = """你是 MyCrew 项目立项助手。唯一职责：把用户的**项目设计需求**拆解为可执行任务。

## 范围限制（硬约束）
- 只回复与具体项目立项 / 工作流设计相关的内容。
- 任何与「设计一个具体项目」无关的提问（闲聊、写诗、百科、教学、代码片段问答、
  心理咨询、政治/敏感话题等）一律礼貌拒绝并提示用户回到项目立项主题，**不要**
  输出 JSON 代码块。

## 何时直接产出方案 vs 何时澄清
- **默认尽量直接产出**。若用户给出**著名项目原型**（俄罗斯方块 / 吃豆人 / 贪吃蛇 /
  打砖块 / Flappy Bird / Tetris / Pac-Man / Snake / Mario / 待办应用 / 计算器 等），
  **直接按合理默认假设产出 JSON**（游戏类默认 Unity + PC + 像素/简约 + 经典玩法）。
- 只有输入**真的极度抽象**（"做个项目"、"帮我做个东西"）才提一个澄清问题。
  **不要为已经明确的需求强行澄清**。

## 技术栈默认值（重要）
- 游戏 / 交互 / 3D / VR / AR 类项目一律默认使用 **Unity**（Unity 2022 LTS 或更
  高、C#、Prefab、ScriptableObject、UGUI/UI Toolkit、Input System、Animator、
  NavMesh、URP 等）。**禁止默认输出 HTML/JavaScript/Canvas/Phaser/Three.js/Pygame
  等 Web 或 Python 游戏栈**，除非用户明确指定。
- 美术资产建模走 Blender，图像生成走 ComfyUI。
- 其他类型项目（脚本、工具、数据处理）按需选择合适栈。

## 任务方案 JSON 协议
当方案成熟时输出一个 ```json 代码块：
{
  "name": "项目名称",
  "execution_kind": "sequential" | "crew" | "flow",
  "tasks": [
    {
      "title": "任务标题",
      "detail": "详细描述（点名所需 Unity 模块 / MCP 工具）",
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
    # Per-session lock. Plan Maker runs are long-running and not naturally
    # serialised — without this, two concurrent /messages or /messages/stream
    # calls for the same session would race on history reads, persist
    # overlapping rows, and confuse the LLM with interleaved context. The
    # frontend already single-flights via useChatQueue; this is the wire-level
    # safety net so the invariant holds even if a future caller bypasses it.
    _session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        return self._session_locks[session_id]

    async def create_session(
        self,
        llm_id: str,
        thinking_mode: bool = False,
        *,
        mode: str = "create",
        parent_project_id: str | None = None,
        template_id: str | None = None,
    ) -> dict:
        """Create an inception session.

        `mode` defaults to "create" (新建项目按钮入口). When mode="iterate"
        the caller must also supply `parent_project_id` — we pre-create
        the iteration project row right here so the user lands in PM
        with root_path + iteration_index already inherited.
        """
        session_data: dict = {
            "llm_id": llm_id,
            "thinking_mode": 1 if thinking_mode else 0,
            "system_prompt": SYSTEM_PROMPT,
            "indexed_paths": "[]",
            "mode": mode,
        }
        # Frontend may pre-bake the template pick (drawer-initial choice
        # panel) so Plan Maker can run on the very first user message
        # without re-asking. Validate against the catalog before storing.
        if template_id:
            from data.unity_templates import get_template
            if get_template(template_id):
                session_data["template_id"] = template_id

        # Iteration entry — create the new project row up front, inheriting
        # root_path / template_id / name (with iteration suffix) from parent.
        if mode == "iterate":
            if not parent_project_id:
                raise ValueError(
                    "mode='iterate' requires parent_project_id (which "
                    "completed project to iterate)"
                )
            parent = await crud.get_by_id("projects", parent_project_id)
            if not parent:
                raise ValueError(f"parent project {parent_project_id} not found")
            parent_iter = int(parent.get("iteration_index") or 1)
            new_index = parent_iter + 1
            new_name = f"{parent.get('name','项目')} · 迭代 v{new_index}"

            from services.project_svc import project_svc
            iter_project = await project_svc.create_project({
                "name": new_name,
                "root_path": parent.get("root_path"),
                "execution_kind": parent.get("execution_kind") or "sequential",
            })
            # Patch iteration metadata that create_project doesn't know about
            await crud.update_by_id("projects", iter_project["id"], {
                "parent_project_id": parent_project_id,
                "iteration_index": new_index,
                "template_id": parent.get("template_id"),
            })
            session_data["project_id"] = iter_project["id"]
            session_data["template_id"] = parent.get("template_id")
            log.info("inception.iteration_session",
                     parent=parent_project_id, child=iter_project["id"],
                     iter=new_index)

        session = await crud.insert("inception_sessions", session_data,
                                     id_prefix="incep_")
        log.info("inception.session_created", id=session["id"], mode=mode)
        return session

    async def apply_choice(
        self,
        session_id: str,
        *,
        template_id: str | None = None,
        root_path: str | None = None,
        mode: str | None = None,
    ) -> dict:
        """Apply a structured choice from the drawer (card click / path picker).

        Updates the session row and broadcasts inception.choice_accepted so
        the drawer can move to the next phase. The actual Plan Maker run
        is deferred until the user sends a free-text message — that way
        Plan Maker always sees the latest pick as session context.
        """
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            raise KeyError(session_id)

        updates: dict = {}
        if template_id:
            # Lazy validation against the static catalog
            from data.unity_templates import get_template
            if not get_template(template_id):
                raise ValueError(f"unknown template_id: {template_id}")
            updates["template_id"] = template_id
        if mode:
            if mode not in ("create", "iterate", "iterate_external"):
                raise ValueError(f"invalid mode: {mode}")
            updates["mode"] = mode
        if root_path is not None:
            # Path goes onto the bound project (if any), not the session
            if session.get("project_id"):
                await crud.update_by_id("projects", session["project_id"],
                                         {"root_path": root_path})

        if updates:
            await crud.update_by_id("inception_sessions", session_id, updates)

        await manager.broadcast("inception.choice_accepted", {
            "session_id": session_id,
            "template_id": template_id,
            "root_path": root_path,
            "mode": mode,
        })

        updated = await crud.get_by_id("inception_sessions", session_id)
        return dict(updated or {})

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
        async with self._lock_for(session_id):
            return await self._send_message_locked(session_id, content)

    async def _send_message_locked(self, session_id: str, content: str) -> dict:
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

        Serialised per session_id so overlapping calls queue up rather than
        racing on history reads / LLM context.
        """
        async with self._lock_for(session_id):
            return await self._stream_message_locked(session_id, content)

    async def _stream_message_locked(self, session_id: str, content: str):
        """Inner implementation; assumes the per-session lock is held.

        Behaviour:
          1. Persist user message + broadcast inception.message.
          2. If a Plan Maker agent exists, run it via CrewAI with the
             create_workflow tool bound to this session_id.
          3. If Plan Maker is missing (fresh DB, etc.), fall back to the
             legacy direct-LLM streaming path.
        """
        await self._probe(session_id, "lock_acquired", content_chars=len(content))
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

        # 1.5 Guard rails — refuse to run Plan Maker until the drawer-side
        # template / root_path choice has been resolved. Re-emits the
        # corresponding choices event so the drawer can recover gracefully
        # if the user free-texted without picking.
        guard = await self._enforce_choice_flow(session_id, session)
        if guard is not None:
            return guard

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
            persisted = await self._persist_salvaged_blueprint(session_id, blueprint)
            if not persisted:
                # Couldn't persist — keep at least the preview event so the
                # frontend can still show the editor in read-only mode.
                await manager.broadcast("inception.tasks_drafted", {
                    "session_id": session_id,
                    "blueprint": blueprint,
                })

        return {"ai_text": full_text, "blueprint": blueprint}

    async def _persist_salvaged_blueprint(
        self, session_id: str, blueprint: dict,
    ) -> bool:
        """Persist a blueprint that was parsed out of raw LLM text (because
        Plan Maker emitted ```json instead of calling create_workflow). Mirrors
        what the tool would have done — so the frontend's blueprint panel
        renders the same way (it requires `inception.workflow_created`).

        Returns True if persisted, False on failure / duplicate."""
        try:
            from services.project_svc import project_svc
        except Exception as exc:
            log.warning("inception.salvage_import_failed", error=str(exc))
            return False

        existing = await crud.get_by_id("inception_sessions", session_id)
        if not existing or existing.get("project_id"):
            return False

        tasks = blueprint.get("tasks") or []
        if not tasks:
            return False

        task_data = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            task_data.append({
                "title": t.get("title", ""),
                "detail": t.get("detail", ""),
                "kind": t.get("kind", "regular"),
                "output_schema": t.get("output_schema", {}),
                "deps": t.get("deps", []),
            })
        if not task_data:
            return False

        try:
            project = await project_svc.create_project_with_tasks(
                data={
                    "name": blueprint.get("name") or f"项目-{session_id[-6:]}",
                    "execution_kind": blueprint.get("execution_kind") or "sequential",
                },
                tasks=task_data,
            )
        except Exception as exc:
            log.warning("inception.salvage_create_failed",
                        session_id=session_id, error=str(exc))
            return False

        await crud.update_by_id("inception_sessions", session_id, {
            "project_id": project["id"],
        })
        await manager.broadcast("inception.workflow_created", {
            "session_id": session_id,
            "project_id": project["id"],
            "project": project,
            "blueprint": {
                **blueprint,
                "name": blueprint.get("name") or project.get("name"),
                "execution_kind": blueprint.get("execution_kind") or "sequential",
            },
        })
        await self._probe(session_id, "salvage_persisted",
                          project_id=project["id"], tasks=len(task_data))
        return True

    async def _finish_if_workflow_created_this_round(
        self,
        session_id: str,
        had_project_before: bool,
        reason: str,
    ) -> dict | None:
        """If the create_workflow tool succeeded during this round (project_id
        flipped from None to set), persist a short confirmation message and
        return — DON'T run the legacy fallback, which would produce an
        unrelated LLM turn whose text contradicts the persisted blueprint.

        Returns the result dict on early-exit, or None if we should fall
        through to the legacy retry path.
        """
        if had_project_before:
            return None
        bound = await crud.get_by_id("inception_sessions", session_id)
        if not bound or not bound.get("project_id"):
            return None
        confirmation = (
            f"✅ 任务方案已生成（{reason}前完成持久化）。"
            "请在右侧蓝图面板中查看并编辑。"
        )
        await crud.insert("inception_messages", {
            "session_id": session_id,
            "role": "assistant",
            "content": confirmation,
        }, id_prefix="msg_")
        await manager.broadcast("inception.message", {
            "session_id": session_id,
            "role": "assistant",
            "content": confirmation,
        })
        await self._probe(session_id, "early_exit_workflow_already_created",
                          reason=reason)
        return {"ai_text": confirmation, "project_id": bound["project_id"]}

    async def _enforce_choice_flow(
        self, session_id: str, session: dict,
    ) -> dict | None:
        """If the session is missing the structured choices Plan Maker
        needs, re-emit the appropriate event and return an early-exit
        dict so the caller skips Plan Maker. Returns None when everything
        is ready and Plan Maker can run.
        """
        mode = (session.get("mode") or "create").lower()

        if mode == "create" and not session.get("template_id"):
            from data.unity_templates import list_templates
            await manager.broadcast("inception.choices", {
                "session_id": session_id,
                "context": "template_selection",
                "prompt": "你想做什么类型的 Unity 游戏？我会基于模板设计任务和架构。",
                "options": [
                    {
                        "value": t["id"],
                        "label": t["label"],
                        "description": t["description"],
                    }
                    for t in list_templates()
                ],
            })
            msg = "请先在上方卡片中选择一个 Unity 模板，我才能设计具体任务。"
            await crud.insert("inception_messages", {
                "session_id": session_id, "role": "assistant", "content": msg,
            }, id_prefix="msg_")
            await manager.broadcast("inception.message", {
                "session_id": session_id, "role": "assistant", "content": msg,
            })
            return {"ai_text": msg, "blueprint": None, "awaiting": "template"}

        if mode == "iterate":
            # Iterate mode needs a known root_path on the bound project
            project_id = session.get("project_id")
            project = (
                await crud.get_by_id("projects", project_id) if project_id else None
            )
            if not project or not (project.get("root_path") or "").strip():
                await manager.broadcast("inception.input_path", {
                    "session_id": session_id,
                    "context": "iteration_root_path",
                    "prompt": "请选择该 Unity 项目的根目录（迭代将基于该路径下的现有资产）。",
                })
                msg = "迭代模式需要项目根目录。请在上方选择路径。"
                await crud.insert("inception_messages", {
                    "session_id": session_id, "role": "assistant",
                    "content": msg,
                }, id_prefix="msg_")
                await manager.broadcast("inception.message", {
                    "session_id": session_id, "role": "assistant",
                    "content": msg,
                })
                return {"ai_text": msg, "blueprint": None,
                        "awaiting": "root_path"}

        return None

    async def _probe(self, session_id: str, label: str, **extra: object) -> None:
        """Emit a checkpoint event. Goes both to structlog and to the WS log
        drawer (event type `inception.probe`) so the user can see exactly
        which step Plan Maker reached when something stalls."""
        log.info(f"inception.probe.{label}", session_id=session_id, **extra)
        try:
            await manager.broadcast("inception.probe", {
                "session_id": session_id,
                "label": label,
                **{k: str(v)[:200] for k, v in extra.items()},
            })
        except Exception as exc:
            log.warning("inception.probe_broadcast_failed", error=str(exc))

    async def _run_plan_maker(
        self,
        session_id: str,
        session: dict,
        content: str,
        plan_maker: dict,
    ) -> dict:
        """Run the Plan Maker CrewAI agent. Every checkpoint emits an
        `inception.probe` event so the LogDrawer shows where execution is."""
        import asyncio
        from crewai import Agent, Crew, Process, Task
        from services.crewai_runner import _build_crewai_llm
        from src.tools.builtin.local.create_workflow import make_create_workflow_tool
        from src.tools.builtin.local.assign_agents import make_assign_agents_tool
        from src.tools.builtin.local.write_blueprint import make_write_blueprint_tool
        from src.tools.builtin.local.workspace import make_workspace_tools
        from bootstrap.seed_plan_maker import render_plan_maker_backstory

        await self._probe(session_id, "enter")

        # Snapshot whether the session already has a workflow attached BEFORE
        # this round. If `create_workflow` fires during the round and we hit
        # a timeout or other failure later, we use this to recognise that
        # the work was already done — and skip the legacy fallback (which
        # would otherwise run a fresh LLM turn whose text contradicts the
        # already-persisted blueprint).
        session_before = await crud.get_by_id("inception_sessions", session_id)
        had_project_before = bool(session_before and session_before.get("project_id"))

        # Resolve LLM: prefer agent's bound LLM, fall back to session's
        llm_id_source = plan_maker.get("llm_id") or session.get("llm_id", "")
        provider_id, model_name = await self._resolve_llm(llm_id_source)
        provider = await crud.get_by_id("llm_providers", provider_id)
        if not provider:
            raise ValueError(f"LLM provider {provider_id} not found")
        await self._probe(session_id, "llm_resolved",
                          provider=provider.get("name"), model=model_name)

        llm = _build_crewai_llm(provider, model_name)
        await self._probe(session_id, "llm_built")

        # Render placeholders in backstory with current MCP + agent inventory
        # + per-session mode context (template skeleton or iteration root)
        rendered_backstory = await render_plan_maker_backstory(
            plan_maker.get("backstory", ""), session=session,
        )
        await self._probe(session_id, "backstory_rendered",
                          chars=len(rendered_backstory))

        # Compose task description: history + new user input
        history = await self._format_history_for_task(session_id)
        description = (
            f"## 当前会话 ID\n{session_id}\n\n"
            f"## 对话历史\n{history}\n\n"
            f"## 用户最新输入\n{content}\n\n"
            "请：(1) 用自然语言回复用户；(2) 当方案明确时调用 create_workflow 工具持久化。"
        )
        await self._probe(session_id, "description_built",
                          history_chars=len(history),
                          description_chars=len(description))

        # Plan Maker needs to call TWO tools in sequence (create_workflow,
        # then assign_agents) and finish with a short confirmation. CrewAI's
        # `max_iter` caps the total LLM rounds, and each tool call consumes
        # one round — so anything below 3 essentially guarantees only the
        # first tool gets called before the agent is forced to stop. Floor
        # at 5 so we have headroom for retries even if the DB row is misset.
        configured_max = int(plan_maker.get("max_retry") or 0)
        max_iter = max(5, configured_max)

        # Iteration mode: give Plan Maker read access to the existing
        # project workspace so it can actually plan around existing assets
        # ("默认复用" requires knowing what's there). Bound to the child
        # iteration project's root_path (inherited from parent on session
        # create). Creation mode gets neither — no root_path exists yet.
        extra_tools: list = []
        if (session.get("mode") or "").lower() in ("iterate", "iterate_external"):
            project_id = session.get("project_id")
            if project_id:
                project_row = await crud.get_by_id("projects", project_id)
                root = project_row.get("root_path") if project_row else None
                if root:
                    ws = make_workspace_tools(root)
                    extra_tools.extend([
                        ws["read_file_local"],
                        ws["list_directory_local"],
                    ])
                    await self._probe(session_id, "iterate_workspace_tools_bound",
                                      root=root)

        agent = Agent(
            role=plan_maker.get("role", "Plan Maker"),
            goal=plan_maker.get("goal", ""),
            backstory=rendered_backstory,
            llm=llm,
            tools=[
                make_create_workflow_tool(session_id),
                make_assign_agents_tool(session_id),
                make_write_blueprint_tool(session_id),
                *extra_tools,
            ],
            max_iter=max_iter,
            verbose=False,
            allow_delegation=False,
        )
        task = Task(
            description=description,
            expected_output=(
                "依次调用 create_workflow + assign_agents 两个工具，然后用一句"
                "中文确认作为最终回复。"
            ),
            agent=agent,
        )
        await self._probe(session_id, "agent_and_task_built")

        # Capture main loop so step_callback (which runs on worker thread)
        # can hop back here to broadcast WS deltas.
        main_loop = asyncio.get_running_loop()
        step_count = {"n": 0}

        def _step_cb(step: object) -> None:
            step_count["n"] += 1
            text = self._extract_text_from_step(step)
            try:
                # Probe → log drawer
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast("inception.probe", {
                        "session_id": session_id,
                        "label": "step",
                        "n": step_count["n"],
                        "preview": (text or "")[:120],
                    }),
                    main_loop,
                )
                # Delta → chat streaming subwindow. Without this, Plan Maker
                # rounds show only "正在思考中" until completion (the legacy
                # path was the only one streaming).
                if text:
                    asyncio.run_coroutine_threadsafe(
                        manager.broadcast("inception.delta", {
                            "session_id": session_id,
                            "text": text + "\n\n",
                        }),
                        main_loop,
                    )
            except Exception as exc:
                log.warning("inception.step_broadcast_failed", error=str(exc))

        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
            memory=False,
            step_callback=_step_cb,
        )
        await self._probe(session_id, "crew_built")

        # No hard timeout — slow LLMs (DeepSeek pro, long-history rounds)
        # can take several minutes; aborting them surprises users more
        # than letting the request breathe. Frontend / user can Stop via
        # the chat queue's abort path if needed.
        try:
            result = await asyncio.to_thread(crew.kickoff)
            await self._probe(session_id, "kickoff_returned",
                              steps=step_count["n"])
        except Exception as exc:
            await self._probe(session_id, "kickoff_failed", error=str(exc)[:200])
            log.warning("inception.crewai_failed_falling_back_to_legacy",
                        session_id=session_id, error=str(exc))
            early = await self._finish_if_workflow_created_this_round(
                session_id, had_project_before,
                reason=f"Plan Maker 中断（{exc}）",
            )
            if early is not None:
                return early
            await manager.broadcast("inception.delta", {
                "session_id": session_id,
                "text": (
                    f"\n⚠️ Plan Maker (CrewAI) 调用失败：{exc}\n"
                    "降级到直连 LLM 流式输出（无工具调用能力）...\n\n"
                ),
            })
            return await self._legacy_stream(session_id, session)

        full_text = str(getattr(result, "raw", result) or "").strip()
        await self._probe(session_id, "result_unpacked", text_chars=len(full_text))

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
        await self._probe(session_id, "assistant_persisted")

        # Fallback: if Plan Maker emitted a JSON block instead of calling
        # the tool, salvage it AND persist it the same way the tool would —
        # otherwise the frontend never sees inception.workflow_created, the
        # blueprint panel stays hidden, and the chat summary falls back to
        # the verbose LLM text. (Plan Maker disobeying the tool-call rule
        # is more common than the prompt suggests.)
        bound = await crud.get_by_id("inception_sessions", session_id)
        if bound and not bound.get("project_id"):
            salvaged = self._try_parse_blueprint(full_text)
            if salvaged:
                log.info("inception.salvaged_blueprint_from_text",
                         session_id=session_id)
                persisted = await self._persist_salvaged_blueprint(
                    session_id, salvaged,
                )
                if not persisted:
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
        # Keep only the last ~8 messages — Plan Maker doesn't need deep history
        # and shorter context = faster LLM rounds (the user's complaint).
        for m in rows[-8:]:
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
