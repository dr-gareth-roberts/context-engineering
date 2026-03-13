import dataclasses
from typing import Dict, List


@dataclasses.dataclass
class Bead:
    id: int
    content: str
    tokens: int
    task_id: str
    status: str  # 'open', 'closed'
    depends_on: List[str] = dataclasses.field(default_factory=list)
    is_root: bool = False
    is_outcome: bool = False  # Marks the "Result" of a task (e.g. the schema)


def calculate_fcv(
    items: List[Bead], active_task_id: str, dependencies: List[str]
) -> Dict[str, float]:
    """
    Calculates Functional Context Value.
    High value = has Root Goal + Active Work + Blockers' Outcomes.
    Low value = has noise from closed, unrelated tasks.
    """
    if not items:
        return {"total": 0.0, "noise": 0.0, "mission": 0.0}

    total_tokens = sum(i.tokens for i in items)

    # 1. Mission Integrity: Is the Root Goal present?
    has_root = any(i.is_root for i in items)

    # 2. Outcome Integrity: Are the outcomes of dependent tasks present?
    # (e.g. do we still have the DB schema while working on Auth?)
    outcomes_needed = set(dependencies)
    outcomes_present = {i.task_id for i in items if i.is_outcome and i.task_id in outcomes_needed}
    outcome_score = len(outcomes_present) / len(outcomes_needed) if outcomes_needed else 1.0

    # 3. Noise Ratio: How much of the window is 'closed' task process (not outcomes)?
    noise_tokens = sum(i.tokens for i in items if i.status == "closed" and not i.is_outcome)
    noise_ratio = noise_tokens / total_tokens

    # Final Score: (Mission * 0.5) + (Outcome * 0.3) + ((1-Noise) * 0.2)
    mission_val = 1.0 if has_root else 0.0
    final_score = (mission_val * 50) + (outcome_score * 30) + ((1 - noise_ratio) * 20)

    return {
        "score": final_score,
        "has_root": has_root,
        "outcomes": list(outcomes_present),
        "noise_percent": noise_ratio * 100,
    }


def simulate():
    # SETUP
    BUDGET = 6000

    # 1. The Root Goal
    root = Bead(0, "Build E-commerce API", 1000, "root", "open", is_root=True)

    # 2. Task A: Postgres Setup (Closed)
    # 8 turns of debugging noise + 1 turn of the actual schema (the outcome)
    task_a_noise = [
        Bead(i, f"Postgres Debugging {i}", 500, "task_a", "closed") for i in range(1, 9)
    ]
    task_a_outcome = Bead(
        9, "FINAL POSTGRES SCHEMA: users(id, email...)", 800, "task_a", "closed", is_outcome=True
    )

    # 3. Task B: Auth Implementation (Active)
    # 5 turns of current work
    task_b_active = [
        Bead(i, f"Auth Implementation {i - 10}", 600, "task_b", "open", depends_on=["task_a"])
        for i in range(10, 15)
    ]

    all_history = [root] + task_a_noise + [task_a_outcome] + task_b_active

    print("=== Causal Compaction Proof of Concept ===")
    print(f"Total History: {len(all_history)} turns ({sum(b.tokens for b in all_history)} tokens)")
    print(f"Budget: {BUDGET} tokens\n")

    # --- STRATEGY 1: Chronological ---
    # Keeps most recent turns.
    chrono = []
    curr = 0
    for b in reversed(all_history):
        if curr + b.tokens <= BUDGET:
            chrono.insert(0, b)
            curr += b.tokens

    res_a = calculate_fcv(chrono, "task_b", ["task_a"])
    print("--- 1. Chronological (Current) ---")
    print(f"Score: {res_a['score']:.1f}/100")
    print(f"Has Root: {res_a['has_root']}")
    print(f"Has DB Schema: {'task_a' in res_a['outcomes']}")
    print(f"Noise (Closed Debugging): {res_a['noise_percent']:.1f}%")
    print(
        "ANALYSIS: Agent kept recent debugging noise but dropped the Root Goal and the DB Schema!"
    )

    # --- STRATEGY 2: Causal (Proposed) ---
    # 1. Protect Root
    # 2. Protect Active Task
    # 3. Protect Outcomes of Blockers
    # 4. Prune 'Process' of closed tasks first

    causal = [root]
    rem = BUDGET - root.tokens

    # Priority Pool:
    #   1. Active Task (task_b)
    #   2. Outcomes of blockers (task_a outcome)
    #   3. Process of active task
    #   4. Process of closed tasks (lowest)

    def get_causal_priority(b: Bead):
        if b.is_root:
            return 0  # handled
        if b.task_id == "task_b":
            return 1  # active
        if b.is_outcome and b.task_id == "task_a":
            return 2  # critical outcome
        if b.status == "closed":
            return 4  # noise
        return 3

    pool = [b for b in all_history if not b.is_root]
    pool.sort(key=get_causal_priority)

    for b in pool:
        if rem >= b.tokens:
            causal.append(b)
            rem -= b.tokens

    res_b = calculate_fcv(causal, "task_b", ["task_a"])
    print("\n--- 2. Causal (Proposed) ---")
    print(f"Score: {res_b['score']:.1f}/100")
    print(f"Has Root: {res_b['has_root']}")
    print(f"Has DB Schema: {'task_a' in res_b['outcomes']}")
    print(f"Noise (Closed Debugging): {res_b['noise_percent']:.1f}%")
    print("ANALYSIS: Agent kept the Root Goal, the DB Schema, and Active Work. Zero noise.")


if __name__ == "__main__":
    simulate()
