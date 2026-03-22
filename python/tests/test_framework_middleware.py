"""Tests for framework middleware — LangChain, LlamaIndex, CrewAI, and generic adapters."""

from context_engineering.framework_middleware import (
    ContextEvent,
    FrameworkMiddlewareOptions,
    with_context_crewai,
    with_context_generic,
    with_context_langchain,
    with_context_llamaindex,
)

# ---------------------------------------------------------------------------
# Mock framework objects (duck-typed, no real framework imports)
# ---------------------------------------------------------------------------


class MockLangChainMessage:
    """Simulates a LangChain BaseMessage with _getType()."""

    def __init__(self, role: str, content: str) -> None:
        self._role = role
        self.content = content

    def _getType(self) -> str:
        return self._role


class MockLangChainModel:
    """Simulates a LangChain ChatModel with invoke()."""

    def __init__(self, model_name: str = "gpt-4o") -> None:
        self.model_name = model_name
        self.last_messages: list = []
        self.call_count = 0

    def invoke(self, messages, **kwargs):
        self.last_messages = messages
        self.call_count += 1
        return {"role": "assistant", "content": "response"}


class MockLlamaIndexMessage:
    """Simulates a LlamaIndex ChatMessage."""

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


class MockLlamaIndexLLM:
    """Simulates a LlamaIndex LLM with chat()."""

    def __init__(self, model: str = "gpt-4o") -> None:
        self.model = model
        self.last_messages: list = []
        self.call_count = 0

    def chat(self, messages=None, **kwargs):
        self.last_messages = messages
        self.call_count += 1
        return {"role": "assistant", "content": "response"}


class MockCrewAILLM:
    """Simulates a CrewAI LLM (uses LangChain under the hood)."""

    def __init__(self, model_name: str = "gpt-4o") -> None:
        self.model_name = model_name
        self.last_messages: list = []
        self.invoke_count = 0
        self.call_count = 0

    def invoke(self, messages, **kwargs):
        self.last_messages = messages
        self.invoke_count += 1
        return {"role": "assistant", "content": "response"}

    def call(self, messages, **kwargs):
        self.last_messages = messages
        self.call_count += 1
        return {"role": "assistant", "content": "response"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_langchain_messages(count: int) -> list[MockLangChainMessage]:
    msgs = [MockLangChainMessage("system", "You are a helpful assistant.")]
    for i in range(count - 1):
        role = "human" if i % 2 == 0 else "ai"
        # Use many distinct words so heuristic tokenizer counts them correctly
        words = " ".join(f"word{j}" for j in range(80))
        msgs.append(MockLangChainMessage(role, f"Message {i}: {words}"))
    return msgs


def _make_llamaindex_messages(count: int) -> list[MockLlamaIndexMessage]:
    msgs = [MockLlamaIndexMessage("system", "You are a helpful assistant.")]
    for i in range(count - 1):
        role = "user" if i % 2 == 0 else "assistant"
        words = " ".join(f"word{j}" for j in range(80))
        msgs.append(MockLlamaIndexMessage(role, f"Message {i}: {words}"))
    return msgs


def _make_dict_messages(count: int) -> list[dict]:
    msgs = [{"role": "system", "content": "You are a helpful assistant."}]
    for i in range(count - 1):
        role = "user" if i % 2 == 0 else "assistant"
        words = " ".join(f"word{j}" for j in range(80))
        msgs.append({"role": role, "content": f"Message {i}: {words}"})
    return msgs


# ---------------------------------------------------------------------------
# LangChain adapter
# ---------------------------------------------------------------------------


class TestLangChainAdapter:
    def test_messages_packed_when_over_budget(self):
        model = MockLangChainModel()
        messages = _make_langchain_messages(20)

        wrapped = with_context_langchain(
            model,
            FrameworkMiddlewareOptions(budget=500, reserve_tokens=100, log=False),
        )
        wrapped.invoke(messages)

        assert model.call_count == 1
        # With a tiny budget, some messages should have been trimmed
        assert len(model.last_messages) < len(messages)

    def test_under_budget_passes_through(self):
        model = MockLangChainModel()
        messages = _make_langchain_messages(3)

        wrapped = with_context_langchain(
            model,
            FrameworkMiddlewareOptions(budget=100_000, log=False),
        )
        wrapped.invoke(messages)

        assert model.call_count == 1
        assert len(model.last_messages) == len(messages)

    def test_event_callback_fires(self):
        events: list[ContextEvent] = []
        model = MockLangChainModel()
        messages = _make_langchain_messages(10)

        wrapped = with_context_langchain(
            model,
            FrameworkMiddlewareOptions(
                budget=500,
                reserve_tokens=100,
                log=False,
                on_pack=lambda e: events.append(e),
            ),
        )
        wrapped.invoke(messages)

        assert len(events) == 1
        assert events[0].framework == "langchain"
        assert events[0].total_messages == len(messages)

    def test_error_fallthrough(self):
        """If packing fails, the original call should still go through."""
        model = MockLangChainModel()
        messages = _make_langchain_messages(5)

        errors: list[Exception] = []

        # Force an error by passing a budget that will trigger packing with
        # a broken on_pack that throws, but the on_error should catch gracefully
        wrapped = with_context_langchain(
            model,
            FrameworkMiddlewareOptions(
                budget=-1,  # invalid but we handle gracefully
                log=False,
                on_error=lambda e: errors.append(e),
            ),
        )
        # Should not raise — should fallthrough to original
        wrapped.invoke(messages)
        assert model.call_count == 1

    def test_empty_messages_passthrough(self):
        model = MockLangChainModel()
        wrapped = with_context_langchain(model, FrameworkMiddlewareOptions(budget=1000, log=False))
        wrapped.invoke([])
        assert model.call_count == 1


# ---------------------------------------------------------------------------
# LlamaIndex adapter
# ---------------------------------------------------------------------------


class TestLlamaIndexAdapter:
    def test_messages_packed_when_over_budget(self):
        llm = MockLlamaIndexLLM()
        messages = _make_llamaindex_messages(20)

        wrapped = with_context_llamaindex(
            llm,
            FrameworkMiddlewareOptions(budget=500, reserve_tokens=100, log=False),
        )
        wrapped.chat(messages=messages)

        assert llm.call_count == 1
        assert len(llm.last_messages) < len(messages)

    def test_under_budget_passes_through(self):
        llm = MockLlamaIndexLLM()
        messages = _make_llamaindex_messages(3)

        wrapped = with_context_llamaindex(
            llm,
            FrameworkMiddlewareOptions(budget=100_000, log=False),
        )
        wrapped.chat(messages=messages)

        assert llm.call_count == 1
        assert len(llm.last_messages) == len(messages)

    def test_event_callback_fires(self):
        events: list[ContextEvent] = []
        llm = MockLlamaIndexLLM()
        messages = _make_llamaindex_messages(10)

        wrapped = with_context_llamaindex(
            llm,
            FrameworkMiddlewareOptions(
                budget=500,
                reserve_tokens=100,
                log=False,
                on_pack=lambda e: events.append(e),
            ),
        )
        wrapped.chat(messages=messages)

        assert len(events) == 1
        assert events[0].framework == "llamaindex"

    def test_positional_arg_messages(self):
        """LlamaIndex chat() can be called with positional args."""
        llm = MockLlamaIndexLLM()
        messages = _make_llamaindex_messages(3)

        wrapped = with_context_llamaindex(
            llm, FrameworkMiddlewareOptions(budget=100_000, log=False)
        )
        wrapped.chat(messages)

        assert llm.call_count == 1
        assert len(llm.last_messages) == len(messages)


# ---------------------------------------------------------------------------
# CrewAI adapter
# ---------------------------------------------------------------------------


class TestCrewAIAdapter:
    def test_invoke_intercepted(self):
        llm = MockCrewAILLM()
        messages = _make_langchain_messages(20)

        wrapped = with_context_crewai(
            llm,
            FrameworkMiddlewareOptions(budget=500, reserve_tokens=100, log=False),
        )
        wrapped.invoke(messages)

        assert llm.invoke_count == 1
        assert len(llm.last_messages) < len(messages)

    def test_call_intercepted(self):
        llm = MockCrewAILLM()
        messages = _make_langchain_messages(20)

        wrapped = with_context_crewai(
            llm,
            FrameworkMiddlewareOptions(budget=500, reserve_tokens=100, log=False),
        )
        wrapped.call(messages)

        assert llm.call_count == 1
        assert len(llm.last_messages) < len(messages)

    def test_under_budget_passes_through(self):
        llm = MockCrewAILLM()
        messages = _make_langchain_messages(3)

        wrapped = with_context_crewai(llm, FrameworkMiddlewareOptions(budget=100_000, log=False))
        wrapped.invoke(messages)

        assert llm.invoke_count == 1
        assert len(llm.last_messages) == len(messages)


# ---------------------------------------------------------------------------
# Generic adapter
# ---------------------------------------------------------------------------


class MockGenericLLM:
    def __init__(self) -> None:
        self.last_messages: list = []
        self.call_count = 0

    def generate(self, messages=None, **kwargs):
        self.last_messages = messages
        self.call_count += 1
        return "response"


class TestGenericAdapter:
    def test_custom_extractors(self):
        llm = MockGenericLLM()
        messages = _make_dict_messages(20)

        wrapped = with_context_generic(
            llm,
            method_name="generate",
            message_extractor=lambda args, kwargs: (
                kwargs.get("messages") or (args[0] if args else [])
            ),
            message_injector=lambda args, kwargs, packed: ((), {**kwargs, "messages": packed}),
            options=FrameworkMiddlewareOptions(budget=500, reserve_tokens=100, log=False),
        )
        wrapped.generate(messages=messages)

        assert llm.call_count == 1
        assert len(llm.last_messages) < len(messages)

    def test_under_budget_passthrough(self):
        llm = MockGenericLLM()
        messages = _make_dict_messages(3)

        wrapped = with_context_generic(
            llm,
            method_name="generate",
            message_extractor=lambda args, kwargs: kwargs.get("messages", []),
            message_injector=lambda args, kwargs, packed: ((), {**kwargs, "messages": packed}),
            options=FrameworkMiddlewareOptions(budget=100_000, log=False),
        )
        wrapped.generate(messages=messages)

        assert llm.call_count == 1
        assert len(llm.last_messages) == len(messages)

    def test_error_fallthrough(self):
        llm = MockGenericLLM()
        messages = _make_dict_messages(5)
        errors: list[Exception] = []

        def bad_extractor(args, kwargs):
            raise RuntimeError("extractor broke")

        wrapped = with_context_generic(
            llm,
            method_name="generate",
            message_extractor=bad_extractor,
            message_injector=lambda args, kwargs, packed: (args, kwargs),
            options=FrameworkMiddlewareOptions(
                budget=1000, log=False, on_error=lambda e: errors.append(e)
            ),
        )
        wrapped.generate(messages=messages)

        assert llm.call_count == 1
        assert len(errors) == 1

    def test_event_callback_fires(self):
        events: list[ContextEvent] = []
        llm = MockGenericLLM()
        messages = _make_dict_messages(10)

        wrapped = with_context_generic(
            llm,
            method_name="generate",
            message_extractor=lambda args, kwargs: kwargs.get("messages", []),
            message_injector=lambda args, kwargs, packed: ((), {**kwargs, "messages": packed}),
            options=FrameworkMiddlewareOptions(
                budget=500,
                reserve_tokens=100,
                log=False,
                on_pack=lambda e: events.append(e),
            ),
            framework_name="my_framework",
        )
        wrapped.generate(messages=messages)

        assert len(events) == 1
        assert events[0].framework == "my_framework"
