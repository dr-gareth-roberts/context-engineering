import dataclasses
from typing import List


@dataclasses.dataclass
class Bead:
    id: int
    content: str
    tokens: int
    task_id: str
    status: str  # 'open' or 'closed'
    is_root_goal: bool = False


def calculate_integrity(items: List[Bead]) -> float:
    """Measures what % of the context is actually relevant to the active goal."""
    if not items:
        return 0.0
    root_present = any(i.is_root_goal for i in items)
    active_tokens = sum(i.tokens for i in items if i.status == "open" or i.is_root_goal)
    total_tokens = sum(i.tokens for i in items)

    # Integrity is high if we have the root goal AND minimal noise from closed tasks
    score = (active_tokens / total_tokens) * 100
    if not root_present:
        score *= 0.1  # Massive penalty for losing the mission objective
    return score


def simulate():
    # 1. Setup the scenario
    # Turn 1: The mission objective (Root)
    root_goal = Bead(
        1, "Build a secure auth system using OAuth2. DO NOT use JWT.", 1000, "main", "open", True
    )

    # Turns 2-10: A side-quest to fix a CI/CD bug (now CLOSED)
    side_quest_noise = [
        Bead(i, f"Debugging CI error line {i}...", 500, "subtask_1", "closed") for i in range(2, 11)
    ]

    # Turns 11-15: Active work on the Auth system
    active_work = [
        Bead(i, f"Implementing OAuth flow step {i - 10}...", 600, "main", "open")
        for i in range(11, 16)
    ]

    all_turns = [root_goal] + side_quest_noise + active_work

    # Budget: 5000 tokens (enough for about 8-9 turns)
    BUDGET = 5000

    print("=== Context Compaction Simulation ===")
    print(f"Total History: {len(all_turns)} turns ({sum(b.tokens for b in all_turns)} tokens)")
    print(f"Budget: {BUDGET} tokens\n")

    # --- STRATEGY A: Chronological Truncation (Current Standard) ---
    # Keeps the most RECENT turns until budget is full.
    chrono_context = []
    current_tokens = 0
    for turn in reversed(all_turns):
        if current_tokens + turn.tokens <= BUDGET:
            chrono_context.insert(0, turn)
            current_tokens += turn.tokens
        else:
            break

    chrono_integrity = calculate_integrity(chrono_context)
    print("--- Strategy A: Chronological (Sliding Window) ---")
    print(f"Turns kept: {[b.id for b in chrono_context]}")
    print(f"Root Goal Present: {any(b.is_root_goal for b in chrono_context)}")
    print(f"Integrity Score: {chrono_integrity:.1f}/100")
    if not any(b.is_root_goal for b in chrono_context):
        print("RESULT: Agent has forgotten the 'No JWT' constraint and the original mission.")

    print("\n--- Strategy B: BEADS Graph-Aware Compaction ---")
    # 1. Protect Root Goal
    # 2. Prioritize Active Tasks
    # 3. Drop Closed Tasks first, regardless of age

    graph_context = [root_goal]
    remaining_budget = BUDGET - root_goal.tokens

    # Sort remaining: Open tasks first, then Closed tasks (if room)
    pool = [b for b in all_turns if not b.is_root_goal]
    pool.sort(key=lambda x: (0 if x.status == "open" else 1, -x.id))  # Open first, then newest

    for turn in pool:
        if remaining_budget >= turn.tokens:
            graph_context.append(turn)
            remaining_budget -= turn.tokens

    graph_integrity = calculate_integrity(graph_context)
    print(f"Turns kept: {[b.id for b in sorted(graph_context, key=lambda x: x.id)]}")
    print(f"Root Goal Present: {any(b.is_root_goal for b in graph_context)}")
    print(f"Integrity Score: {graph_integrity:.1f}/100")
    print("RESULT: Agent maintains mission objective and active work. Noise is pruned.")


if __name__ == "__main__":
    simulate()
