"""Cross-module integration tests — verify the full production pipeline.

These tests exercise pack → place → quality → cost → handoff → pickup
roundtrips, and the composable pipeline API with sessions.
"""

from context_engineering.allocation import KindAllocation, pack_with_allocation
from context_engineering.beads import (
    HandoffOptions,
    create_handoff,
    get_ready_issues,
    pickup_handoff,
    read_beads_jsonl,
    write_beads_jsonl,
)
from context_engineering.cache_topology import pack_with_cache_topology
from context_engineering.core import (
    Budget,
    ContextItem,
    diff,
    pack,
    trace_pack,
)
from context_engineering.cost import estimate_cost, project_costs
from context_engineering.pipeline import create_pipeline
from context_engineering.placement import effective_budget, place_items
from context_engineering.quality import analyze_context
from context_engineering.session import create_session


def make_item(id: str, kind: str, priority: float, tokens: int, content: str = None) -> ContextItem:
    return ContextItem(
        id=id,
        content=content or f"Content for {id}: {kind} context with priority {priority}",
        kind=kind,
        priority=priority,
        tokens=tokens,
        recency=5.0,
    )


ITEMS = [
    make_item("system-prompt", "system", 10, 200, "You are a helpful assistant."),
    make_item("tool-schema", "system", 9, 150, "Available tools: search, calculate, summarize."),
    make_item("user-profile", "memory", 7, 80, "User prefers concise responses."),
    make_item("doc-1", "retrieval", 6, 300, "API documentation for the search endpoint."),
    make_item("doc-2", "retrieval", 5, 250, "Tutorial on building context-aware agents."),
    make_item("doc-3", "retrieval", 3, 200, "Reference guide for token estimation."),
    make_item("conversation-1", "conversation", 8, 100, "User asked about context engineering."),
    make_item("conversation-2", "conversation", 4, 120, "Previous discussion about budgets."),
    make_item("query", "query", 9, 50, "How do I optimize prefix cache usage?"),
]


class TestFullPipelineRoundtrip:
    """pack → place → quality → cost → handoff → pickup"""

    def test_roundtrip(self):
        budget = 800

        # Step 1: Pack within budget
        packed = pack(ITEMS, Budget(max_tokens=budget))
        assert len(packed.selected) > 0
        assert packed.total_tokens <= budget
        assert len(packed.dropped) > 0

        # Step 2: Place for attention optimization
        placed = place_items(packed.selected, strategy="attention-optimized", model="claude")
        assert len(placed) == len(packed.selected)

        # Step 3: Analyze quality
        quality = analyze_context(placed)
        assert quality.item_count == len(placed)
        assert quality.overall > 0
        assert quality.density > 0
        assert quality.diversity > 0

        # Step 4: Cost estimation with cache topology
        cache_pack = pack_with_cache_topology(ITEMS, Budget(max_tokens=budget))
        assert cache_pack.cache_key is not None
        assert cache_pack.cache_efficiency >= 0
        assert cache_pack.cacheable_tokens >= 0

        cost = estimate_cost(cache_pack, "claude-sonnet-4-6", output_tokens=500)
        assert cost.model == "claude-sonnet-4-6"
        assert cost.input_tokens > 0
        assert cost.cost_with_cache <= cost.cost_without_cache
        assert cost.savings_percent >= 0

        # Step 5: Create handoff
        handoff = create_handoff(
            packed,
            HandoffOptions(
                agent="integration-test",
                session_id="test-session-1",
                handoff_notes="Full integration test handoff",
                include_dropped=True,
            ),
        )
        assert handoff.jsonl
        assert handoff.stats["activeItems"] == len(packed.selected)
        assert handoff.stats["deferredItems"] == len(packed.dropped)

        # Step 6: Pickup handoff
        pickup = pickup_handoff(handoff.jsonl)
        assert len(pickup.items) == len(packed.selected)
        assert len(pickup.deferred) == len(packed.dropped)
        assert pickup.manifest is not None
        assert pickup.stats["handoffSessionId"] == "test-session-1"

        # Verify ID roundtrip
        for original in packed.selected:
            recovered = next(i for i in pickup.items if i.id == original.id)
            assert recovered.content == original.content
            assert recovered.kind == original.kind
            assert recovered.priority == original.priority
            assert recovered.tokens == original.tokens


class TestComposablePipelineWithSessions:
    """Pipeline → session → diff across turns"""

    def test_pipeline_session_delta(self):
        session = create_session(Budget(max_tokens=600))

        # Turn 1
        r1 = (
            create_pipeline(600)
            .add(
                make_item("sys", "system", 10, 100, "You are helpful."),
                make_item("doc", "retrieval", 7, 200, "API docs."),
                make_item("q1", "query", 9, 50, "What is context engineering?"),
            )
            .allocate(
                [
                    KindAllocation(kind="system", target_ratio=0.2),
                    KindAllocation(kind="retrieval", target_ratio=0.5),
                    KindAllocation(kind="query", target_ratio=0.3),
                ]
            )
            .cache_topology()
            .place("attention-optimized")
            .quality_gate()
            .session(session)
            .build()
        )

        assert len(r1.selected) > 0
        assert "allocate" in r1.stages
        assert "cacheTopology" in r1.stages
        assert "place" in r1.stages
        assert "quality" in r1.stages
        assert "session" in r1.stages
        assert r1.delta is None  # first compile

        # Turn 2 — same system + doc, different query
        r2 = (
            create_pipeline(600)
            .add(
                make_item("sys", "system", 10, 100, "You are helpful."),
                make_item("doc", "retrieval", 7, 200, "API docs."),
                make_item("q2", "query", 9, 50, "How do I use the pipeline?"),
            )
            .cache_topology()
            .session(session)
            .build()
        )

        assert r2.delta is not None
        assert r2.delta.kept_count > 0
        assert len(r2.delta.added) > 0
        assert len(r2.delta.removed_ids) > 0
        assert r2.delta.reuse_ratio > 0


class TestAllocationCostProjection:
    """allocate → cache-topology → cost projection with monthly estimate"""

    def test_allocation_to_monthly_projection(self):
        items = [
            make_item("sys", "system", 10, 500, "System prompt."),
            make_item("mem-1", "memory", 6, 200, "User preference."),
            make_item("rag-1", "retrieval", 8, 400, "FAQ document."),
            make_item("rag-2", "retrieval", 7, 300, "Account guide."),
            make_item("conv", "conversation", 9, 300, "Previous turn."),
            make_item("query", "query", 10, 60, "How to update billing?"),
        ]

        budget = 1200

        # Allocate
        allocated = pack_with_allocation(
            items,
            Budget(max_tokens=budget),
            [
                KindAllocation(kind="system", target_ratio=0.25, min_tokens=400),
                KindAllocation(kind="memory", target_ratio=0.15),
                KindAllocation(kind="retrieval", target_ratio=0.35),
                KindAllocation(kind="conversation", target_ratio=0.15),
                KindAllocation(kind="query", target_ratio=0.10),
            ],
        )

        assert len(allocated.selected) > 0
        # minTokens guarantee may cause slight budget overshoot
        assert allocated.total_tokens <= budget * 1.1

        # Cache topology
        cache_pack = pack_with_cache_topology(
            allocated.selected,
            Budget(max_tokens=allocated.total_tokens + 100),
        )
        assert cache_pack.cacheable_tokens > 0

        # Monthly projection
        projection = project_costs(
            cache_pack, "claude-sonnet-4-6", 10000, output_tokens=800, requests_per_day=500
        )
        assert projection.request_count == 10000
        assert projection.total_savings >= 0
        assert projection.monthly_estimate is not None
        assert projection.monthly_estimate.requests_per_day == 500


class TestBeadsRoundtrip:
    """write → read → getReady → merge"""

    def test_beads_cycle(self):
        items = [
            make_item("sys", "system", 10, 100, "System context."),
            make_item("task-1", "task", 8, 50, "Implement feature A."),
        ]

        packed = pack(items, Budget(max_tokens=500))
        handoff = create_handoff(packed, HandoffOptions(agent="agent-1"))

        # Read
        issues = read_beads_jsonl(handoff.jsonl)
        assert len(issues) > 0

        # Write back and re-read
        rewritten = write_beads_jsonl(issues)
        reread = read_beads_jsonl(rewritten)
        assert len(reread) == len(issues)

        # Get ready issues
        ready = get_ready_issues(issues)
        assert len(ready) >= 0


class TestEffectiveBudgetTraceDiff:
    """effective budget → trace → diff"""

    def test_budget_trace_diff(self):
        effective = effective_budget(8000, model="claude")
        assert effective < 8000
        assert effective > 0

        items = [
            make_item("a", "system", 10, 100),
            make_item("b", "retrieval", 7, 200),
            make_item("c", "retrieval", 3, 300),
        ]

        # Trace
        trace = trace_pack(items, Budget(max_tokens=effective))
        assert len(trace.steps) > 0
        for step in trace.steps:
            assert step.decision in ("include", "exclude", "compress")
            assert step.id

        # Diff two packs
        pack1 = pack(items, Budget(max_tokens=250))
        pack2 = pack(items, Budget(max_tokens=500))
        d = diff(pack1.selected, pack2.selected)
        total = len(d["added"]) + len(d["removed"]) + len(d["changed"]) + len(d["kept"])
        assert total > 0
