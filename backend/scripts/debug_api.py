"""Check that the service layer returns what the inspect script shows."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.repo.sqlite_repo import init_db, close_db
from services.llm_svc import llm_svc
from services.mcp_svc import mcp_svc
from services.agent_svc import agent_svc
from services.crew_svc import crew_svc
from services.tool_svc import tool_svc


async def main() -> None:
    await init_db()
    print("\n## llm_svc.list_providers()")
    providers = await llm_svc.list_providers()
    print(f"  count: {len(providers)}")
    for p in providers[:2]:
        print(f"  sample: {json.dumps(p, default=str, ensure_ascii=False)[:200]}")

    print("\n## mcp_svc.list_servers()")
    servers = await mcp_svc.list_servers()
    print(f"  count: {len(servers)}")
    for s in servers[:2]:
        print(f"  sample: {json.dumps(s, default=str, ensure_ascii=False)[:200]}")

    print("\n## agent_svc.list_agents()")
    agents = await agent_svc.list_agents()
    print(f"  count: {len(agents)}")
    for a in agents[:2]:
        print(f"  sample: {json.dumps(a, default=str, ensure_ascii=False)[:200]}")

    print("\n## crew_svc.list_crews()")
    crews = await crew_svc.list_crews()
    print(f"  count: {len(crews)}")

    print("\n## tool_svc.list_tools()")
    tools = await tool_svc.list_tools()
    print(f"  count: {len(tools)}")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
