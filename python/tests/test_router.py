"""Tests for model router — complexity analysis, routing, and adaptive learning."""

from context_engineering.core import Budget, ContextItem
from context_engineering.router import (
    ModelTier,
    analyze_complexity,
    create_adaptive_router,
    create_context_router,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(id: str, content: str, **kwargs) -> ContextItem:
    return ContextItem(id=id, content=content, **kwargs)


def _default_tiers() -> list[ModelTier]:
    return [
        ModelTier(
            model="cheap-model",
            max_complexity=0.3,
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
            max_tokens=4000,
            capabilities=["text"],
        ),
        ModelTier(
            model="mid-model",
            max_complexity=0.6,
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.03,
            max_tokens=16000,
            capabilities=["text", "code"],
        ),
        ModelTier(
            model="expensive-model",
            max_complexity=1.0,
            cost_per_1k_input=0.06,
            cost_per_1k_output=0.12,
            max_tokens=200000,
            capabilities=["text", "code", "vision", "reasoning"],
        ),
    ]


# ---------------------------------------------------------------------------
# Complexity analysis
# ---------------------------------------------------------------------------


class TestAnalyzeComplexity:
    def test_empty_items_returns_zero(self):
        result = analyze_complexity([])

        assert result.overall == 0.0
        assert result.diversity == 0.0

    def test_simple_items_low_complexity(self):
        items = [
            _make_item("a", "hello world", tokens=5),
            _make_item("b", "goodbye world", tokens=5),
        ]

        result = analyze_complexity(items)

        assert result.overall < 0.5

    def test_dependency_depth_increases_complexity(self):
        items = [
            _make_item("a", "base item content", tokens=10),
            _make_item("b", "depends on base", tokens=10, dependsOn=["a"]),
            _make_item("c", "depends on b", tokens=10, dependsOn=["b"]),
            _make_item("d", "depends on c", tokens=10, dependsOn=["c"]),
        ]

        result = analyze_complexity(items)

        assert result.dependency_depth > 0.0

    def test_tool_calls_increase_complexity(self):
        items = [
            _make_item("a", "regular content", tokens=10, kind="docs"),
            _make_item("b", "tool invocation result", tokens=10, kind="tool"),
            _make_item("c", "another tool result", tokens=10, kind="tool_result"),
            _make_item("d", "function call output", tokens=10, kind="function_call"),
        ]

        result = analyze_complexity(items)

        assert result.tool_call_count > 0.0

    def test_multilinguality_detection(self):
        items = [
            _make_item("en", "hello world good morning", tokens=10),
            _make_item("zh", "\u4f60\u597d\u4e16\u754c\u65e9\u4e0a\u597d", tokens=10),
        ]

        result = analyze_complexity(items)

        assert result.multilinguality > 0.0

    def test_custom_weights(self):
        items = [
            _make_item("a", "content with some depth", tokens=50),
            _make_item("b", "more content here", tokens=50, dependsOn=["a"]),
        ]

        result_default = analyze_complexity(items)
        result_custom = analyze_complexity(
            items,
            weights={
                "diversity": 0.0,
                "density": 0.0,
                "dependency_depth": 1.0,
                "tool_call_count": 0.0,
                "multilinguality": 0.0,
                "average_item_length": 0.0,
            },
        )

        # Custom weights emphasizing only dependency depth should differ.
        assert result_custom.overall != result_default.overall


# ---------------------------------------------------------------------------
# ContextRouter
# ---------------------------------------------------------------------------


class TestContextRouter:
    def test_routes_simple_to_cheapest(self):
        items = [
            _make_item("a", "hello", tokens=5),
            _make_item("b", "world", tokens=5),
        ]
        router = create_context_router(_default_tiers())

        decision = router.route(items, Budget(maxTokens=1000))

        assert decision.model == "cheap-model"
        assert decision.estimated_cost_input > 0

    def test_routes_complex_to_capable_model(self):
        items = [
            _make_item(
                f"item-{i}",
                f"complex content number {i} with many tokens " * 20,
                tokens=500,
                dependsOn=[f"item-{i - 1}"] if i > 0 else [],
            )
            for i in range(10)
        ]
        # Add tool kinds to boost complexity.
        for i in range(5):
            items[i] = items[i].model_copy(update={"kind": "tool"})

        router = create_context_router(_default_tiers())

        decision = router.route(items, Budget(maxTokens=100000))

        # Should route to a more capable model due to high complexity.
        assert decision.model in ("mid-model", "expensive-model")

    def test_falls_back_to_default(self):
        items = [
            _make_item("a", "content " * 100, tokens=5000),
        ]
        # Only one tier that's too small.
        tiers = [
            ModelTier(
                model="tiny",
                max_complexity=0.1,
                cost_per_1k_input=0.001,
                cost_per_1k_output=0.001,
                max_tokens=100,
            ),
        ]
        router = create_context_router(tiers, default_model="tiny")

        decision = router.route(items, Budget(maxTokens=10000))

        assert decision.model == "tiny"

    def test_respects_max_tokens(self):
        items = [
            _make_item("a", "content", tokens=5000),
        ]
        tiers = [
            ModelTier(
                model="small",
                max_complexity=1.0,
                cost_per_1k_input=0.001,
                cost_per_1k_output=0.001,
                max_tokens=1000,
            ),
            ModelTier(
                model="large",
                max_complexity=1.0,
                cost_per_1k_input=0.01,
                cost_per_1k_output=0.01,
                max_tokens=100000,
            ),
        ]
        router = create_context_router(tiers)

        decision = router.route(items, Budget(maxTokens=10000))

        # "small" can't fit 5000 tokens.
        assert decision.model == "large"

    def test_respects_capabilities(self):
        items = [_make_item("a", "hello", tokens=5)]
        router = create_context_router(_default_tiers())

        decision = router.route(items, Budget(maxTokens=1000), required_capabilities=["vision"])

        # Only expensive-model has vision capability.
        assert decision.model == "expensive-model"

    def test_provides_alternative_model(self):
        items = [_make_item("a", "hello", tokens=5)]
        router = create_context_router(_default_tiers())

        decision = router.route(items, Budget(maxTokens=1000))

        # Should have an alternative.
        assert decision.alternative_model is not None
        assert decision.alternative_cost_delta is not None

    def test_reasoning_is_populated(self):
        items = [_make_item("a", "hello", tokens=5)]
        router = create_context_router(_default_tiers())

        decision = router.route(items, Budget(maxTokens=1000))

        assert len(decision.reasoning) > 0
        assert "cheap-model" in decision.reasoning


# ---------------------------------------------------------------------------
# AdaptiveRouter
# ---------------------------------------------------------------------------


class TestAdaptiveRouter:
    def test_adaptive_router_routes(self):
        router = create_adaptive_router(_default_tiers())
        items = [_make_item("a", "hello world", tokens=5)]

        decision = router.route(items, Budget(maxTokens=1000))

        assert decision.model is not None

    def test_adaptive_router_records_outcomes(self):
        router = create_adaptive_router(_default_tiers(), min_samples=2)
        items = [_make_item("a", "hello world", tokens=5)]

        decision = router.route(items, Budget(maxTokens=1000))
        router.report_outcome(decision, 0.9)

        insights = router.get_insights()
        assert insights.total_decisions == 1
        assert decision.model in insights.model_stats

    def test_adaptive_router_computes_insights(self):
        router = create_adaptive_router(_default_tiers(), min_samples=2)
        items = [_make_item("a", "hello world simple content", tokens=5)]

        for _ in range(5):
            decision = router.route(items, Budget(maxTokens=1000))
            router.report_outcome(decision, 0.85)

        insights = router.get_insights()
        assert insights.total_decisions == 5
        assert insights.model_stats[decision.model]["uses"] == 5.0

    def test_adaptive_router_detects_potential_savings(self):
        tiers = [
            ModelTier(
                model="cheap",
                max_complexity=0.3,
                cost_per_1k_input=0.001,
                cost_per_1k_output=0.001,
                max_tokens=4000,
            ),
            ModelTier(
                model="expensive",
                max_complexity=1.0,
                cost_per_1k_input=0.1,
                cost_per_1k_output=0.1,
                max_tokens=100000,
            ),
        ]
        router = create_adaptive_router(tiers, min_samples=3)

        # Route simple items but force to expensive by making tokens exceed cheap max.
        items_big = [_make_item("a", "content " * 100, tokens=5000)]

        for _ in range(5):
            decision = router.route(items_big, Budget(maxTokens=10000))
            # Report high quality — showing expensive model works but cheap might too.
            router.report_outcome(decision, 0.9)

        insights = router.get_insights()
        assert insights.total_decisions == 5

    def test_complexity_breakdown_has_all_dimensions(self):
        items = [
            _make_item("a", "content one", tokens=10),
            _make_item("b", "content two", tokens=10),
        ]

        breakdown = analyze_complexity(items)

        assert hasattr(breakdown, "diversity")
        assert hasattr(breakdown, "density")
        assert hasattr(breakdown, "dependency_depth")
        assert hasattr(breakdown, "tool_call_count")
        assert hasattr(breakdown, "multilinguality")
        assert hasattr(breakdown, "average_item_length")
        assert hasattr(breakdown, "overall")
