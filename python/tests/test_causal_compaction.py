import pytest
from context_engineering.compaction import ContextManager
from context_engineering.core import Budget

def test_causal_compaction_prioritization():
    # 1. Setup Manager with a small budget (approx 4 turns if each is 500)
    # Budget = 2500
    ctx = ContextManager(
        budget=Budget(maxTokens=2500),
        system_prompt="System",
        token_estimator=lambda x: 500, # Fixed size for testing
        preserve_recent_turns=0
    )

    # 2. Define the Task Graph
    graph = [
        {"id": "root", "title": "Mission", "status": "open"},
        {"id": "task-a", "title": "Old Task", "status": "closed"},
        {"id": "task-b", "title": "New Task", "status": "open"},
    ]

    ctx.set_beads_graph(graph)
    ctx.set_active_task("task-b")

    # 3. Add Turns
    ctx.add_turn("user", "GOAL: Build a house.", task_id="root")
    
    # 5 noise turns from task-a
    for i in range(5):
        ctx.add_turn("assistant", f"Debugging plumbing {i}...", task_id="task-a")

    # 1 active turn from task-b
    ctx.add_turn("user", "Now starting on the roof.", task_id="task-b")

    # 4. Compile
    result = ctx.compile()

    # 5. Verify
    contents = [t.content for t in result.turns]
    
    # Must have the Root Goal
    assert "GOAL: Build a house." in contents
    # Must have the Active work
    assert "Now starting on the roof." in contents
    
    # Root (500) + Active (500) + System (??) = 1000+
    # Budget 2500 can fit at most 2-3 noise turns.
    assert len(result.turns) <= 5

    # Check order
    timestamps = [t.timestamp for t in result.turns]
    assert timestamps == sorted(timestamps)

def test_causal_compaction_protect_outcomes():
    # Noise = 500, Outcome = 800
    def custom_estimator(text):
        if "Outcome" in text or "ARCHITECTURE" in text:
            return 800
        return 500

    ctx = ContextManager(
        budget=Budget(maxTokens=1500),
        token_estimator=custom_estimator,
        preserve_recent_turns=0
    )

    graph = [
        {"id": "task-a", "title": "Old Task", "status": "closed"},
    ]
    ctx.set_beads_graph(graph)

    # Add noise
    ctx.add_turn("assistant", "Noise 1", task_id="task-a")
    ctx.add_turn("assistant", "Noise 2", task_id="task-a")
    
    # Add outcome
    ctx.add_turn("assistant", "Outcome: FINAL ARCHITECTURE", task_id="task-a", is_outcome=True)

    result = ctx.compile()
    contents = [t.content for t in result.turns]

    # Outcome should be protected by its 1.5x multiplier vs noise 0.1x
    assert "Outcome: FINAL ARCHITECTURE" in contents
