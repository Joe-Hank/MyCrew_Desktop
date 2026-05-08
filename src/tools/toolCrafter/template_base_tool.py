"""
CrewAI BaseTool 子类模板（完整版）
===================================

适用范围
--------
- 默认首选。当你不确定选哪种规格时用这个。
- 支持全部可配置项：name / description / args_schema / cache_function /
  result_as_answer / max_usage_count / 异步执行 / 动态 description 等。
- 适合中到高复杂度的 Tool（访问文件系统、调用外部 API、封装 MCP 工具等）。

使用方式
--------
1. 将本文件复制到 `src/tools/` 或 `src/tools/builtin/xxx/` 下并重命名
   （例如 `web_search_tool.py`）。
2. 删除所有带 `# TEMPLATE:` 前缀的说明性注释。
3. 填写【核心配置项】区块（必填）。
4. 按需启用或删除【可选配置项】区块。
5. 在 `_run()` 内实现同步业务逻辑；如有 IO 密集型/异步场景可额外实现 `_arun()`。

依赖
----
- crewai >= 0.100.0
- pydantic >= 2.0

参考
----
- CrewAI Tools: https://docs.crewai.com/concepts/tools
- BaseTool 源码: https://github.com/crewAIInc/crewAI/blob/main/src/crewai/tools/base_tool.py
"""

from __future__ import annotations

# TEMPLATE: 根据实际业务需要导入第三方包；删除未用的 import 可减少启动开销
from typing import Any, Type

from pydantic import BaseModel, Field, field_validator
from crewai.tools import BaseTool


# =============================================================================
# 1) 输入参数 Schema（args_schema）
# =============================================================================
# 说明：
#   - `args_schema` 对 Agent 调用本 Tool 时的参数做 Pydantic 校验。
#   - 不写 args_schema 时，CrewAI 会从 `_run()` 签名反射推断，但 **强烈建议显式定义**
#     复杂/高风险 Tool 的 schema，以便参数错误在调用前被 Pydantic 拦截。
#   - 每个字段的 `description` 会合入到 Tool 的函数签名并喂给 LLM，写清楚语义与边界。
# =============================================================================

class MyToolArgs(BaseModel):
    """TEMPLATE: 替换为你的 Tool 参数定义。"""

    # TEMPLATE: 示例字段 1 —— 必填字符串
    query: str = Field(
        ...,
        description="要执行的查询关键词",
        min_length=1,
        max_length=500,
    )

    # TEMPLATE: 示例字段 2 —— 带默认值与约束的整数
    top_k: int = Field(
        default=5,
        description="返回结果的最大条数",
        ge=1,
        le=50,
    )

    # TEMPLATE: 示例字段 3 —— 可选字段（Optional 或 None 默认）
    # filter_tag: str | None = Field(default=None, description="可选的标签过滤")

    # TEMPLATE: 自定义校验器（可选）。删除即可。
    @field_validator("query")
    @classmethod
    def _strip_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query 不能为空白字符串")
        return v


# =============================================================================
# 2) 缓存函数（cache_function）—— 可选
# =============================================================================
# 说明：
#   - `cache_function(args: dict, result: Any) -> bool` 返回 True 时本次结果进缓存；
#     返回 False 时本次结果不进缓存（例如"错误/空结果不缓存"）。
#   - 需要 `Crew(cache=True)` 才会真正启用缓存。
# =============================================================================

def _my_tool_cache(args: dict, result: Any) -> bool:
    """TEMPLATE: 自定义缓存策略；不用可整块删除，并移除下方 `cache_function=` 行。"""
    # 示例：空字符串或以 "ERROR" 开头的结果不缓存
    if not result:
        return False
    if isinstance(result, str) and result.startswith("ERROR"):
        return False
    return True


# =============================================================================
# 3) Tool 主类
# =============================================================================

class MyTool(BaseTool):
    """TEMPLATE: 一句话说明本 Tool 的作用（给开发者看）。"""

    # -------------------------------------------------------------------------
    # 【核心配置项】—— 必填
    # -------------------------------------------------------------------------

    # name: Tool 的唯一标识；Agent/LLM 通过它引用。
    #   - 规则：同进程内唯一，snake_case，`[a-zA-Z0-9_]`。
    name: str = "my_tool"

    # description: 能力描述，直接注入 LLM prompt。
    #   - 必须清楚写明：做什么 / 何时该用 / 输入输出是什么。
    #   - 建议用简洁英文或中文都行，但所在项目 LLM 能理解即可。
    description: str = (
        "TEMPLATE: 说明本 Tool 的能力、适用场景与输入输出约定。"
        "例：在本地知识库中按关键词做语义搜索，返回 top-k 条带元数据的命中。"
    )

    # -------------------------------------------------------------------------
    # 【可选配置项】—— 不用的可直接删除（不要保留 None 占位）
    # -------------------------------------------------------------------------

    # args_schema: 入参 Pydantic 模型。
    #   - 不显式写时由 CrewAI 从 `_run` 反射生成。
    #   - 复杂场景强烈建议显式给出以获得更好的错误信息。
    args_schema: Type[BaseModel] = MyToolArgs

    # cache_function: 自定义缓存策略，见上文 `_my_tool_cache`。
    #   - 需要 `Crew(cache=True)` 才会生效。
    cache_function = staticmethod(_my_tool_cache)  # noqa: E501

    # result_as_answer: 若为 True，Agent 会把本 Tool 的返回值 **直接作为 task 最终输出**
    #   而不再交给 LLM 做一次"润色/复述"。适合：
    #     - 返回结构化报表/JSON
    #     - 返回文件路径/二进制句柄
    #     - 任何 LLM 改写反而会破坏信息的场景
    result_as_answer: bool = False

    # max_usage_count: 单个 Task 生命周期内，本 Tool 允许被调用的最大次数（防死循环）。
    #   - 不设或设为 0 → CrewAI 不限次数。
    max_usage_count: int = 0

    # current_usage_count: 运行时计数器；通常不手动设置。
    #   - 留在此处仅为示范全部字段；生产代码一般删掉本行。
    current_usage_count: int = 0

    # description_updated: 描述是否被运行时动态更新的标记位。
    #   - 同上，通常不手动设置，此处仅为说明存在该字段。
    description_updated: bool = False

    # -------------------------------------------------------------------------
    # 【核心配置项】—— 必填：同步执行体
    # -------------------------------------------------------------------------

    def _run(self, **kwargs: Any) -> Any:
        """执行本 Tool 的同步逻辑。

        - 入参类型：由 `args_schema` 校验后以 kwargs 形式传入；也可改成显式签名
          `def _run(self, query: str, top_k: int = 5)` 以获得静态类型提示。
        - 返回值：可以是任意可 `str()` 序列化的 Python 对象；CrewAI 会把它转成字符串
          喂给 LLM。建议返回 `str` 或能 `json.dumps` 的 dict/list 以避免歧义。
        - 异常：在 `_run` 内抛出异常时，CrewAI 会捕获并把错误消息回喂给 LLM，让
          Agent 自行决定是否重试。业务上若希望"硬失败"，可直接 raise 让上层 workflow 感知。
        """
        # TEMPLATE: 替换为真实业务逻辑
        query: str = kwargs["query"]
        top_k: int = kwargs.get("top_k", 5)

        # 示例：占位实现
        result = f"[MyTool] query={query!r} top_k={top_k}"
        return result

    # -------------------------------------------------------------------------
    # 【可选配置项】—— 异步执行体
    # -------------------------------------------------------------------------
    # 说明：
    #   - 如果 Tool 内部是 IO 密集型（HTTP/数据库/MCP），强烈建议实现 `_arun`。
    #   - CrewAI 运行时检测到协程时会优先调用异步版本，可显著提升并发吞吐。
    #   - 同步 `_run` 仍需保留作为回退（部分编排路径只走同步）。
    # -------------------------------------------------------------------------

    async def _arun(self, **kwargs: Any) -> Any:
        """异步执行体；若不用可整段删除。"""
        # TEMPLATE: 示例 —— 真实项目中通常是 `await http_client.get(...)` 这类
        import asyncio
        await asyncio.sleep(0)  # 占位
        return self._run(**kwargs)


# =============================================================================
# 4) 模块导出约定
# =============================================================================
# - 每个 Tool 文件 **必须**在模块顶层暴露一个 BaseTool 子类（本例为 `MyTool`）。
# - 建议同时暴露一个实例常量，便于 `from ... import my_tool` 直接拿到单例：
# =============================================================================

my_tool = MyTool()

__all__ = ["MyTool", "MyToolArgs", "my_tool"]
