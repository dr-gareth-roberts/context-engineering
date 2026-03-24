"""Tests for the context compiler module."""

from __future__ import annotations

from context_engineering.compiler import (
    Constraint,
    Slot,
    context_program,
    create_context_compiler,
    optimize_for_target,
    validate_constraints,
)
from context_engineering.core import Budget, ContextItem


def _item(id: str, content: str, **kwargs) -> ContextItem:
    tokens = kwargs.pop("tokens", max(1, round(len(content.split()) * 1.3)))
    return ContextItem(id=id, content=content, tokens=tokens, **kwargs)


class TestContextProgramBuilder:
    def test_creates_empty_program(self):
        program = context_program().build()
        assert program.slots == []
        assert program.constraints == []

    def test_declares_slot_with_all_options(self):
        program = (
            context_program()
            .declare(
                "system",
                kind="system",
                required=True,
                position="first",
                max_tokens=2000,
                min_tokens=100,
                fill_remaining=False,
                strategy="priority",
                deduplicate=True,
                max_staleness=3600,
            )
            .build()
        )
        assert len(program.slots) == 1
        s = program.slots[0]
        assert s.name == "system"
        assert s.kind == "system"
        assert s.required is True
        assert s.position == "first"
        assert s.max_tokens == 2000

    def test_declares_multiple_slots_and_constraints(self):
        program = (
            context_program()
            .declare("system", kind="system", required=True, position="first")
            .declare("code", kind="code", strategy="relevance")
            .constraint("coverage")
            .constraint("max-redundancy", threshold=0.3)
            .build()
        )
        assert len(program.slots) == 2
        assert len(program.constraints) == 2

    def test_build_returns_copies(self):
        builder = context_program().declare("x", kind="x")
        p1 = builder.build()
        p2 = builder.build()
        p1.slots.append(Slot(name="injected", kind="injected"))
        assert len(p2.slots) == 1


class TestValidateConstraints:
    def test_no_contradiction_detects_negation_mismatch(self):
        items = [
            _item("a", "you should always use strict mode in typescript projects", kind="rules"),
            _item(
                "b",
                "you should never not use strict mode in typescript projects avoid",
                kind="rules",
            ),
        ]
        slots = [Slot(name="rules", kind="rules")]
        constraints = [Constraint(type="no-contradiction", slots=["rules"])]
        budget = Budget(max_tokens=10000)

        diags = validate_constraints(items, constraints, slots, budget)
        assert any(d.constraint == "no-contradiction" for d in diags)

    def test_freshness_flags_stale_items(self):
        items = [
            _item("a", "old information here", kind="data", recency=2),
            _item("b", "fresh information here", kind="data", recency=8),
        ]
        slots = [Slot(name="data", kind="data")]
        constraints = [Constraint(type="freshness", slots=["data"], threshold=5)]
        budget = Budget(max_tokens=10000)

        diags = validate_constraints(items, constraints, slots, budget)
        assert len(diags) == 1
        assert diags[0].constraint == "freshness"

    def test_coverage_flags_missing_required_slots(self):
        items = [_item("a", "some code content", kind="code")]
        slots = [
            Slot(name="system", kind="system", required=True),
            Slot(name="code", kind="code"),
        ]
        constraints = [Constraint(type="coverage")]
        budget = Budget(max_tokens=10000)

        diags = validate_constraints(items, constraints, slots, budget)
        assert len(diags) == 1
        assert diags[0].level == "error"
        assert diags[0].slot == "system"

    def test_budget_utilization_flags_low_usage(self):
        items = [_item("a", "tiny", kind="data", tokens=100)]
        slots = [Slot(name="data", kind="data")]
        constraints = [Constraint(type="budget-utilization", threshold=0.7)]
        budget = Budget(max_tokens=10000)

        diags = validate_constraints(items, constraints, slots, budget)
        assert any(d.constraint == "budget-utilization" for d in diags)

    def test_max_redundancy_flags_overlapping_items(self):
        items = [
            _item("a", "the quick brown fox jumps over the lazy dog today", kind="data"),
            _item("b", "the quick brown fox jumps over the lazy dog tomorrow", kind="data"),
        ]
        slots = [Slot(name="data", kind="data")]
        constraints = [Constraint(type="max-redundancy", slots=["data"], threshold=0.5)]
        budget = Budget(max_tokens=10000)

        diags = validate_constraints(items, constraints, slots, budget)
        assert any(d.constraint == "max-redundancy" for d in diags)


class TestOptimizer:
    def test_position_aware_placement_first_last(self):
        items = [
            _item("hist1", "history entry", kind="history"),
            _item("code1", "code block", kind="code"),
            _item("sys1", "system prompt", kind="system"),
        ]
        slots = [
            Slot(name="system", kind="system", position="first"),
            Slot(name="code", kind="code"),
            Slot(name="history", kind="history", position="last"),
        ]

        result, passes = optimize_for_target(items, "generic", slots)
        assert result[0].kind == "system"
        assert result[-1].kind == "history"

    def test_staleness_pruning_removes_stale(self):
        items = [
            _item("a", "old content from long ago", kind="data", recency=1),
            _item("b", "fresh content from now", kind="data", recency=8),
        ]
        slots = [Slot(name="data", kind="data", max_staleness=5)]

        result, _ = optimize_for_target(items, "generic", slots)
        assert len(result) == 1
        assert result[0].id == "b"

    def test_different_targets_different_orderings(self):
        items = [
            _item(f"item-{i}", f"content for item number {i}", kind="code", priority=i * 2)
            for i in range(6)
        ]
        slots = [Slot(name="code", kind="code")]

        claude_result, _ = optimize_for_target(items, "claude", slots)
        gpt_result, _ = optimize_for_target(items, "gpt4", slots)

        claude_ids = [i.id for i in claude_result]
        gpt_ids = [i.id for i in gpt_result]
        assert claude_ids != gpt_ids


class TestCompiler:
    def test_compile_simple_program(self):
        compiler = create_context_compiler()
        program = (
            context_program()
            .declare("system", kind="system", required=True, position="first")
            .declare("code", kind="code")
            .constraint("coverage")
            .build()
        )
        items = [
            _item("sys1", "You are a helpful assistant", kind="system", tokens=10),
            _item("code1", "function hello() { return 1; }", kind="code", tokens=15),
        ]

        result = compiler.compile(program, "claude", items, Budget(max_tokens=1000))
        assert len(result.items) > 0
        assert result.target == "claude"
        assert result.total_tokens > 0
        assert result.quality is not None

    def test_drops_items_exceeding_budget(self):
        compiler = create_context_compiler()
        program = context_program().declare("code", kind="code").build()
        items = [
            _item("a", "first item", kind="code", tokens=50),
            _item("b", "second item", kind="code", tokens=50),
            _item("c", "third item", kind="code", tokens=50),
        ]

        result = compiler.compile(program, "generic", items, Budget(max_tokens=100))
        assert len(result.items) < 3
        assert len(result.dropped) > 0

    def test_error_diagnostic_for_unsatisfied_required_slot(self):
        compiler = create_context_compiler()
        program = (
            context_program()
            .declare("system", kind="system", required=True)
            .declare("code", kind="code")
            .build()
        )
        items = [_item("code1", "some code", kind="code", tokens=10)]

        result = compiler.compile(program, "generic", items, Budget(max_tokens=1000))
        errors = [d for d in result.diagnostics if d.level == "error"]
        assert len(errors) > 0

    def test_fill_remaining_gets_leftover_budget(self):
        compiler = create_context_compiler()
        program = (
            context_program()
            .declare("system", kind="system", max_tokens=100)
            .declare("extra", kind="extra", fill_remaining=True)
            .build()
        )
        items = [
            _item("sys1", "system prompt", kind="system", tokens=50),
            _item("extra1", "extra content a", kind="extra", tokens=200),
        ]

        result = compiler.compile(program, "generic", items, Budget(max_tokens=500))
        assert result.slots["system"].tokens_used == 50
        assert result.slots["extra"].tokens_used > 0

    def test_handles_empty_items(self):
        compiler = create_context_compiler()
        program = context_program().declare("code", kind="code").build()

        result = compiler.compile(program, "generic", [], Budget(max_tokens=1000))
        assert result.items == []
        assert result.total_tokens == 0

    def test_uncategorized_items_dropped_without_fill_remaining(self):
        compiler = create_context_compiler()
        program = context_program().declare("code", kind="code").build()
        items = [_item("a", "orphan item", kind="unknown", tokens=10)]

        result = compiler.compile(program, "generic", items, Budget(max_tokens=1000))
        assert len(result.dropped) == 1

    def test_returns_slot_breakdown(self):
        compiler = create_context_compiler()
        program = (
            context_program().declare("system", kind="system").declare("code", kind="code").build()
        )
        items = [
            _item("sys1", "system prompt here", kind="system", tokens=20),
            _item("code1", "code block here", kind="code", tokens=30),
        ]

        result = compiler.compile(program, "generic", items, Budget(max_tokens=1000))
        assert "system" in result.slots
        assert result.slots["system"].item_count == 1
        assert result.slots["system"].tokens_used == 20

    def test_respects_reserve_tokens(self):
        compiler = create_context_compiler()
        program = context_program().declare("code", kind="code").build()
        items = [
            _item("a", "content a", kind="code", tokens=50),
            _item("b", "content b", kind="code", tokens=50),
        ]

        result = compiler.compile(
            program, "generic", items, Budget(max_tokens=120, reserve_tokens=40)
        )
        assert len(result.items) == 1
        assert result.total_tokens <= 80
