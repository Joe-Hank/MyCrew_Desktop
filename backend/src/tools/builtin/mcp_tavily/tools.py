"""Tavily MCP tool bridges (web search / fetch / research).

Targets `tavily-mcp` (npx -y tavily-mcp@latest). Discovered_tools in DB:
  - tavily_search   → general web search
  - tavily_extract  → fetch + clean a single URL
  - tavily_research → multi-step research (slower, deeper)
  - tavily_crawl    → site crawl (skipped: niche)
  - tavily_map      → site map (skipped: niche)

We bridge the three most useful for an agent that needs to look up
information or pull reference content into a deliverable.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


_SERVER = "tavily"


class TavilySearchArgs(BaseModel):
    query: str = Field(..., description="Search query.")
    max_results: int = Field(5, description="Max results (1-20, default 5).")
    search_depth: str = Field(
        "basic",
        description='"basic" (fast, default) or "advanced" (slower, higher quality).',
    )


class TavilySearch(GuardedMCPTool):
    name: str = "tavily_search"
    description: str = (
        "Search the web via Tavily. Returns titles, URLs, and content "
        "snippets. Use for quick fact-finding or reference lookups."
    )
    args_schema: type[BaseModel] = TavilySearchArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "tavily_search"

    def _run(self, query: str, max_results: int = 5, search_depth: str = "basic") -> str:
        return self._guarded_call({
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
        })


class TavilyExtractArgs(BaseModel):
    urls: list[str] = Field(..., description="One or more URLs to fetch.")


class TavilyExtract(GuardedMCPTool):
    name: str = "tavily_extract"
    description: str = (
        "Fetch and clean the main content of one or more URLs (strips "
        "boilerplate, returns readable text). Use after tavily_search "
        "when you need the full article, not just the snippet."
    )
    args_schema: type[BaseModel] = TavilyExtractArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "tavily_extract"

    def _run(self, urls: list[str]) -> str:
        return self._guarded_call({"urls": urls})


class TavilyResearchArgs(BaseModel):
    query: str = Field(..., description="High-level research question.")
    max_results: int = Field(8, description="Max sources (default 8).")


class TavilyResearch(GuardedMCPTool):
    name: str = "tavily_research"
    description: str = (
        "Multi-step research on a topic — Tavily runs sub-queries, "
        "synthesizes findings, and returns a structured brief. Slower "
        "than tavily_search; use for hard background questions."
    )
    args_schema: type[BaseModel] = TavilyResearchArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "tavily_research"

    def _run(self, query: str, max_results: int = 8) -> str:
        return self._guarded_call({"query": query, "max_results": max_results})


__all__ = ["TavilySearch", "TavilyExtract", "TavilyResearch"]
