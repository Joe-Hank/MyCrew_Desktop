"""Test that all LLM modules import correctly."""
import sys
sys.path.insert(0, ".")


def test_base_imports():
    from infra.llm.base import (
        BaseLLMAdapter, LlmConfig, LlmMessage, LlmResponse, LlmDelta, LlmUsage
    )
    assert LlmConfig is not None
    assert LlmMessage is not None

    # Test dataclass creation
    msg = LlmMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"

    config = LlmConfig(
        provider_type="openai",
        api_key="test-key",
        model_name="gpt-4",
    )
    assert config.provider_type == "openai"
    assert config.max_tokens == 4096  # default
    assert config.temperature == 0.7  # default


def test_registry_imports():
    from infra.llm.registry import get_adapter, create_adapter
    from infra.llm.openai_adapter import OpenAICompatibleAdapter
    from infra.llm.anthropic_adapter import AnthropicAdapter

    # Test registry resolves correctly
    assert get_adapter("openai") is OpenAICompatibleAdapter
    assert get_adapter("deepseek") is OpenAICompatibleAdapter
    assert get_adapter("qwen") is OpenAICompatibleAdapter
    assert get_adapter("anthropic") is AnthropicAdapter
    # Unknown falls back to OpenAI
    assert get_adapter("unknown_provider") is OpenAICompatibleAdapter


def test_create_adapter():
    from infra.llm.base import LlmConfig
    from infra.llm.registry import create_adapter
    from infra.llm.openai_adapter import OpenAICompatibleAdapter
    from infra.llm.anthropic_adapter import AnthropicAdapter

    config_openai = LlmConfig(
        provider_type="openai",
        api_key="sk-test",
        model_name="gpt-4o",
    )
    adapter = create_adapter(config_openai)
    assert isinstance(adapter, OpenAICompatibleAdapter)

    config_anthropic = LlmConfig(
        provider_type="anthropic",
        api_key="sk-ant-test",
        model_name="claude-3-5-sonnet-20241022",
    )
    adapter = create_adapter(config_anthropic)
    assert isinstance(adapter, AnthropicAdapter)


def test_openai_adapter_build_body():
    from infra.llm.base import LlmConfig, LlmMessage
    from infra.llm.openai_adapter import OpenAICompatibleAdapter

    config = LlmConfig(
        provider_type="deepseek",
        api_key="sk-test",
        model_name="deepseek-chat",
        max_tokens=8192,
    )
    adapter = OpenAICompatibleAdapter(config)

    messages = [
        LlmMessage(role="system", content="You are helpful."),
        LlmMessage(role="user", content="Hello"),
    ]
    body = adapter._build_body(messages)

    assert body["model"] == "deepseek-chat"
    assert body["max_tokens"] == 8192
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


def test_anthropic_adapter_build_body():
    from infra.llm.base import LlmConfig, LlmMessage
    from infra.llm.anthropic_adapter import AnthropicAdapter

    config = LlmConfig(
        provider_type="anthropic",
        api_key="sk-ant-test",
        model_name="claude-3-5-sonnet-20241022",
        max_tokens=4096,
    )
    adapter = AnthropicAdapter(config)

    messages = [
        LlmMessage(role="system", content="You are helpful."),
        LlmMessage(role="user", content="Hello"),
    ]
    body = adapter._build_body(messages)

    # Anthropic separates system from messages
    assert body["model"] == "claude-3-5-sonnet-20241022"
    assert body["system"] == "You are helpful."
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"


def test_anthropic_thinking_mode():
    from infra.llm.base import LlmConfig, LlmMessage
    from infra.llm.anthropic_adapter import AnthropicAdapter

    config = LlmConfig(
        provider_type="anthropic",
        api_key="sk-ant-test",
        model_name="claude-3-5-sonnet-20241022",
        max_tokens=8192,
        supports_thinking=True,
        thinking_mode=True,
    )
    adapter = AnthropicAdapter(config)

    messages = [LlmMessage(role="user", content="Think about this")]
    body = adapter._build_body(messages)

    assert "thinking" in body
    assert body["thinking"]["type"] == "enabled"
    assert body["temperature"] == 1.0  # Must be 1 when thinking enabled


def test_gateway_import():
    from infra.llm.gateway import LlmGateway, llm_gateway
    assert llm_gateway is not None
    assert isinstance(llm_gateway, LlmGateway)


if __name__ == "__main__":
    test_base_imports()
    print("✓ base imports")
    test_registry_imports()
    print("✓ registry imports")
    test_create_adapter()
    print("✓ create_adapter")
    test_openai_adapter_build_body()
    print("✓ openai build_body")
    test_anthropic_adapter_build_body()
    print("✓ anthropic build_body")
    test_anthropic_thinking_mode()
    print("✓ anthropic thinking mode")
    test_gateway_import()
    print("✓ gateway import")
    print("\nAll tests passed!")
