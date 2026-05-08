"""
CrewAI StructuredTool 模板（LangChain 兼容层）
================================================

适用范围
--------
- 需要 **严格 Pydantic 校验** 且希望与 LangChain 生态互操作的场景。
- 把已有 LangChain StructuredTool 迁入 CrewAI 时，改动最小。
- 需要在同一个 Tool 上同时提供同步 + 异步实现（`func` + `coroutine`）。
- 需要在运行时动态构造 Tool（不想写 class，用工厂函数 `from_function` 一行搞定）。

什么时候 **不要** 用
-------------------
- 纯 CrewAI 项目、不需要 LangChain 互操作 → 用 `template_base_tool.py`（更原生）。
- 逻辑极简 → 用 `template_decorator_tool.py`。

使用方式
--------
1. 复制本文件到 `src/tools/` 或 `src/tools/builtin/xxx/` 下并重命名。
2. 删除所有 `# TEMPLATE:` 注释。
3. 填写【核心配置项】区块。
4. 按需启用或删除【可选配置项】区块。
5. 实现 `_run()` 内的同步逻辑；如有异步需求实现 `_arun()`。

依赖
----
- crewai >= 0.100.0
- pydantic >= 2.0

参考
----
- CrewAI Tools: https://docs.crewai.com/concepts/tools
- CrewStructuredTool 源码: crewai/tools/structured_tool.py
- LangChain StructuredTool: https://python.langchain.com/docs/modules/tools/custom_tools/
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator
from crewai.tools.structured_tool import CrewStructuredTool


# =============================================================================
# 1) 输入参数 Schema（args_schema）—— 核心配置项
# =============================================================================
# 说明：
#   - StructuredTool 的核心优势就是 **强制要求** args_schema，不允许省略。
#   - 每个字段的 `description` 会被注入 LLM prompt，写清楚语义与约束。
#   - 支持嵌套 BaseModel、联合类型（Union）、Literal 枚举等复杂结构。
# =============================================================================

class MyStructuredToolArgs(BaseModel):
    """TEMPLATE: 替换为你的 Tool 参数定义。"""

    # TEMPLATE: 示例字段 1 —— 必填字符串
    url: str = Field(
        ...,
        description="要请求的目标 URL（必须以 http:// 或 https:// 开头）",
    )

    # TEMPLATE: 示例字段 2 —— 带默认值的枚举
    method: str = Field(
        default="GET",
        description="HTTP 方法，支持 GET / POST / PUT / DELETE",
        pattern=r"^(GET|POST|PUT|DELETE)$",
    )

    # TEMPLATE: 示例字段 3 —— 可选复杂类型
    headers: dict[str, str] | None = Field(
        default=None,
        description="自定义请求头（键值对）",
    )

    # TEMPLATE: 示例字段 4 —— 可选 body
    body: str | None = Field(
        default=None,
        description="请求体内容（仅 POST/PUT 时有效）",
    )

    # TEMPLATE: 自定义校验器（可选）
    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("url 必须以 http:// 或 https:// 开头")
        return v


# =============================================================================
# 2) 同步执行函数
# =============================================================================

def _my_structured_tool_run(url: str, method: str = "GET", headers: dict[str, str] | None = None, body: str | None = None) -> str:
    """TEMPLATE: 同步执行逻辑。

    注意：
    - 函数签名必须与 args_schema 的字段一一对应（名称 + 类型）。
    - 返回值会被 CrewAI 序列化为字符串喂给 LLM。
    """
    # TEMPLATE: 替换为真实业务逻辑
    return f"[MyStructuredTool] {method} {url} headers={headers} body_len={len(body) if body else 0}"


# =============================================================================
# 3) 异步执行函数 —— 可选配置项
# =============================================================================
# 说明：
#   - 定义后 CrewAI 在异步编排路径中会优先调用此协程。
#   - 签名必须与同步版本一致。
#   - 不需要异步可整段删除，并移除下方 `coroutine=` 行。
# =============================================================================

async def _my_structured_tool_arun(url: str, method: str = "GET", headers: dict[str, str] | None = None, body: str | None = None) -> str:
    """TEMPLATE: 异步执行逻辑；不用可整段删除。"""
    # TEMPLATE: 真实项目中通常是 `async with httpx.AsyncClient() as client: ...`
    import asyncio
    await asyncio.sleep(0)  # 占位
    return _my_structured_tool_run(url, method, headers, body)


# =============================================================================
# 4) 构造 StructuredTool 实例
# =============================================================================
# 说明：
#   CrewStructuredTool.from_function() 是推荐的工厂方法，一行完成构造。
#   也可以直接实例化 CrewStructuredTool(...)，效果相同。
# =============================================================================

my_structured_tool = CrewStructuredTool.from_function(
    # -------------------------------------------------------------------------
    # 【核心配置项】—— 必填
    # -------------------------------------------------------------------------

    # name: Tool 唯一标识，snake_case，同进程内唯一。
    name="my_structured_tool",

    # description: 能力描述，直接进 LLM prompt。
    description=(
        "TEMPLATE: 说明本 Tool 的能力、适用场景与输入输出约定。"
        "例：发送 HTTP 请求到指定 URL 并返回响应体文本。"
    ),

    # func: 同步执行函数引用。
    func=_my_structured_tool_run,

    # args_schema: Pydantic 输入 schema（StructuredTool 必填）。
    args_schema=MyStructuredToolArgs,

    # -------------------------------------------------------------------------
    # 【可选配置项】—— 不用的可直接删除对应行
    # -------------------------------------------------------------------------

    # coroutine: 异步执行函数引用；不需要异步可删除此行。
    coroutine=_my_structured_tool_arun,

    # result_as_answer: 若为 True，Agent 直接把返回值作为 task 最终输出。
    #   适合返回结构化报表/文件路径等不希望 LLM 改写的场景。
    # result_as_answer=False,

    # return_direct: LangChain 兼容字段，等价于 result_as_answer。
    #   建议只用 result_as_answer（CrewAI 原生），避免两者冲突。
    # return_direct=False,
)


# =============================================================================
# 5) 缓存函数 —— 可选配置项
# =============================================================================
# 说明：
#   StructuredTool 的 cache_function 需要在实例化后赋值（from_function 不接收此参数）。
#   需要 `Crew(cache=True)` 才会真正启用。
# =============================================================================

def _my_structured_cache(args: dict, result: Any) -> bool:
    """TEMPLATE: 自定义缓存策略；不用可整块删除。"""
    # 示例：4xx/5xx 状态码的响应不缓存
    if isinstance(result, str) and result.startswith("ERROR"):
        return False
    return True


# TEMPLATE: 启用缓存策略（不用可删除下面这行）
my_structured_tool.cache_function = _my_structured_cache  # type: ignore[attr-defined]


# =============================================================================
# 6) 模块导出约定
# =============================================================================
# - 后端扫描器会在模块顶层寻找 BaseTool / CrewStructuredTool 实例。
# - `my_structured_tool` 已经是可用的 Tool 对象。
# =============================================================================

__all__ = ["MyStructuredToolArgs", "my_structured_tool"]
