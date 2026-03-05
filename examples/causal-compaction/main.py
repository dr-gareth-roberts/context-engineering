from context_engineering import ContextManager, Budget
import json
import time

# CAUSAL COMPACTION EXAMPLE (Python)
# Demonstrates mission integrity via graph-aware pruning.

# 1. Define a mock BEADS graph (as a list of dicts)
graph = [
    {"id": "root", "title": "Build a secure Auth system", "status": "open"},
    {"id": "task-a", "title": "Debug CI/CD pipeline", "status": "closed"},
    {"id": "task-b", "title": "Implement OAuth2 flow", "status": "open"}
]

# 2. Initialize the Context Manager
ctx = ContextManager(
    budget=Budget(maxTokens=2000),
    system_prompt="You are a secure coding expert.",
    preserve_recent_turns=1
)

ctx.set_beads_graph(graph)
ctx.set_active_task("task-b")

print("--- Phase 1: Adding History ---")

# Add the Mission Goal
ctx.add_turn("user", "CRITICAL: Build the Auth system using OAuth2. DO NOT use JWT.", task_id="root")

# Add noise from a closed task
for i in range(1, 6):
    ctx.add_turn("assistant", f"Fixed CI error #{i} by updating the dockerfile...", task_id="task-a")

# Add the active work
ctx.add_turn("user", "I'm starting on the OAuth flow now.", task_id="task-b")

print("\n--- Phase 2: Compiling Context ---")
result = ctx.compile()

print(f"\nBudget: 2000 tokens")
print(f"Total turns in history: {ctx.turn_count()}")
print(f"Turns kept after causal compaction: {len(result.turns)}")

print("\n--- Active Context Window ---")
for i, turn in enumerate(result.turns):
    print(f"{i+1}. [{turn.role}] (Task: {turn.task_id}): {turn.content[:60]}...")

# Observation:
# Causal Graph-Aware Compaction ensures the 'root' goal is never dropped, 
# even when 1000s of tokens of 'noise' from task-a are added later.
