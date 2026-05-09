from __future__ import annotations

import structlog

log = structlog.get_logger()


class InceptionService:
    async def create_session(self, llm_id: str, thinking_mode: bool = False) -> dict:
        raise NotImplementedError

    async def list_sessions(self) -> list[dict]:
        return []

    async def send_message(self, session_id: str, content: str):
        raise NotImplementedError

    async def index_path(self, session_id: str, path: str) -> dict:
        raise NotImplementedError

    async def finalize(self, session_id: str) -> dict:
        raise NotImplementedError


inception_svc = InceptionService()
