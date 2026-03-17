"""Tests for prompt templating."""

from context_engineering.core import create_context_item
from context_engineering.template import (
    DEFAULT_SECTION_RULES,
    PromptTemplateConfig,
    compile_to_messages,
    format_for_anthropic,
    format_for_openai,
    to_messages,
)


class TestToMessages:
    def test_system_kind_maps_to_system_role(self):
        items = [create_context_item("s1", "system prompt", kind="system")]
        result = to_messages(items)
        assert len(result.messages) == 1
        assert result.messages[0].role == "system"

    def test_query_kind_maps_to_user_role(self):
        items = [create_context_item("q1", "what is AI?", kind="query")]
        result = to_messages(items)
        assert result.messages[0].role == "user"

    def test_retrieval_gets_prefix(self):
        items = [create_context_item("r1", "retrieved doc", kind="retrieval")]
        result = to_messages(items)
        assert "[Retrieved]" in result.messages[0].content

    def test_unknown_kind_uses_fallback(self):
        items = [create_context_item("x1", "mystery", kind="custom_kind")]
        result = to_messages(items)
        assert result.messages[0].role == "system"  # default fallback

    def test_custom_fallback_role(self):
        items = [create_context_item("x1", "mystery", kind="custom_kind")]
        config = PromptTemplateConfig(fallback_role="user")
        result = to_messages(items, config)
        assert result.messages[0].role == "user"

    def test_merge_combines_items(self):
        items = [
            create_context_item("s1", "first system", kind="system"),
            create_context_item("s2", "second system", kind="system"),
        ]
        result = to_messages(items)
        system_msgs = [m for m in result.messages if m.role == "system"]
        assert len(system_msgs) == 1
        assert "first system" in system_msgs[0].content
        assert "second system" in system_msgs[0].content

    def test_metadata_role_overrides(self):
        items = [create_context_item("s1", "override me", kind="system", metadata={"role": "user"})]
        result = to_messages(items)
        assert result.messages[0].role == "user"

    def test_empty_input(self):
        result = to_messages([])
        assert len(result.messages) == 0

    def test_stats_present(self):
        items = [
            create_context_item("s1", "system text", kind="system"),
            create_context_item("q1", "user text", kind="query"),
        ]
        result = to_messages(items)
        assert hasattr(result.stats, "section_counts")
        assert hasattr(result.stats, "system_tokens")
        assert hasattr(result.stats, "user_tokens")

    def test_included_item_ids(self):
        items = [
            create_context_item("alpha", "one", kind="system"),
            create_context_item("beta", "two", kind="query"),
        ]
        result = to_messages(items)
        assert "alpha" in result.included_item_ids
        assert "beta" in result.included_item_ids


class TestFormatForAnthropic:
    def test_extracts_system(self):
        items = [
            create_context_item("s1", "system instructions", kind="system"),
            create_context_item("q1", "user question", kind="query"),
        ]
        prompt = to_messages(items)
        result = format_for_anthropic(prompt)
        assert "system instructions" in result.system
        assert all(m["role"] != "system" for m in result.messages)

    def test_empty_system(self):
        items = [create_context_item("q1", "question", kind="query")]
        prompt = to_messages(items)
        result = format_for_anthropic(prompt)
        assert result.system == ""


class TestFormatForOpenAI:
    def test_system_first(self):
        items = [
            create_context_item("q1", "question", kind="query"),
            create_context_item("s1", "system msg", kind="system"),
        ]
        prompt = to_messages(items)
        result = format_for_openai(prompt)
        system_indices = [i for i, m in enumerate(result.messages) if m["role"] == "system"]
        non_system_indices = [i for i, m in enumerate(result.messages) if m["role"] != "system"]
        if system_indices and non_system_indices:
            assert system_indices[0] < non_system_indices[0]


class TestCompileToMessages:
    def test_turns_to_messages(self):
        compiled = {
            "turns": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
            "items": [],
            "total_tokens": 0,
        }
        result = compile_to_messages(compiled)
        assert any(m.content == "hello" for m in result.messages)
        assert any(m.content == "hi there" for m in result.messages)

    def test_items_included(self):
        compiled = {
            "turns": [{"role": "user", "content": "hello"}],
            "items": [create_context_item("s1", "system context", kind="system")],
            "total_tokens": 0,
        }
        result = compile_to_messages(compiled)
        assert len(result.messages) > 1


class TestDefaultSectionRules:
    def test_has_rules(self):
        assert len(DEFAULT_SECTION_RULES) > 0
        system_rule = next(r for r in DEFAULT_SECTION_RULES if r.kind == "system")
        assert system_rule.role == "system"
        assert system_rule.merge is True
