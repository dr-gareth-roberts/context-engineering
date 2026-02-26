import asyncio

from context_engineering import (
    BoundaryProtector,
    ContextItem,
    ScoringWeights,
    StructuralSegmenter,
)
from context_engineering.eval import Backtester, EvalCase


async def main():
    print("=== THE CONTEXT TORTURE TEST SUITE (v2.2) ===")

    tester = Backtester(redundancy_threshold=0.99999)

    # 1. Recursive Negation (Chain)
    tester.add_case(
        EvalCase(
            name="Negation Chain recursion",
            items=[
                ContextItem(id="v1", content="Val 1", priority=5.0),
                ContextItem(id="v2", content="Val 2", priority=6.0, supersedes="v1"),
                ContextItem(id="v3", content="Val 3", priority=7.0, supersedes="v2"),
            ],
            budget=1000,
            required_ids={"v3"},
            disallowed_ids={"v1", "v2"},
        )
    )

    # 2. Semantic Mirrors
    tester.add_case(
        EvalCase(
            name="Semantic Mirror Integrity",
            items=[
                ContextItem(
                    id="on", content="Reactor is ENABLED.", priority=9.0, embedding=[1.0, 0.0]
                ),
                ContextItem(
                    id="off", content="Reactor is DISABLED.", priority=9.0, embedding=[1.0, 0.01]
                ),
            ],
            budget=1000,
            required_ids={"on", "off"},
        )
    )

    # 3. Hierarchical Inversion
    # Force budget to ONLY fit one item.
    tester.add_case(
        EvalCase(
            name="Hierarchical Inversion",
            items=[
                ContextItem(id="root", content="Summary doc " * 20, priority=1.0),  # ~40 tokens
                ContextItem(
                    id="key", content="SECRET KEY 12345 " * 20, priority=10.0, parent_id="root"
                ),  # ~60 tokens
            ],
            budget=70,
            required_ids={"key"},
            disallowed_ids={"root"},
        )
    )

    # 4. Relational Syphon
    tester.add_case(
        EvalCase(
            name="Relational Syphon",
            items=[
                ContextItem(id="A", content="Core A " * 20, priority=10.0),  # ~40 tokens
                ContextItem(
                    id="B", content="Linked B " * 20, priority=1.0, links=["A"]
                ),  # ~40 tokens
                ContextItem(
                    id="noise", content="High Priority Noise " * 20, priority=8.0
                ),  # ~40 tokens
            ],
            budget=90,  # Fits exactly two. Should be A and B (due to boost), NOT noise.
            required_ids={"A", "B"},
            disallowed_ids={"noise"},
            weights=ScoringWeights(relation_boost=15.0),
        )
    )

    results = tester.run_all()
    tester.print_report(results)

    print("\n--- Manual Entity Split Verification ---")
    protector = BoundaryProtector()
    messy_text = "Analysis of system v4.12.0-rc1 and node 550e8400-e29b-41d4-a716-446655440000."
    seg = StructuralSegmenter(max_tokens=10, protector=protector)
    segments = seg.segment(messy_text)
    split_detected = False
    for s in segments:
        if "v4.12.0" in s.content and "rc1" not in s.content:
            split_detected = True
        if "550e8400" in s.content and "446655440000" not in s.content:
            split_detected = True

    if split_detected:
        print("FAILED: Protected entity was split.")
    else:
        print("PASSED: Protected entities remained atomic.")


if __name__ == "__main__":
    asyncio.run(main())
