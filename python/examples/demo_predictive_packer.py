from dataclasses import dataclass
from typing import Dict, List, Set


# Simulated Context Engineering classes based on the repository's logic
@dataclass
class ContextItem:
    id: str
    content: str
    tokens: int
    kind: str


class CacheTopologySimulator:
    def __init__(self, provider="anthropic"):
        self.provider = provider
        self.history_hashes: Set[str] = set()

        # Anthropic caching rules:
        # Minimum prefix length: 1024 tokens
        self.min_prefix = 1024

    def hash_prefix(self, items: List[ContextItem]) -> str:
        # Simplistic hash: join IDs and lengths
        return "|".join(f"{i.id}:{i.tokens}" for i in items)

    def evaluate_pack(
        self, static_items: List[ContextItem], volatile_items: List[ContextItem]
    ) -> Dict[str, float]:
        static_tokens = sum(i.tokens for i in static_items)
        volatile_tokens = sum(i.tokens for i in volatile_items)
        total_tokens = static_tokens + volatile_tokens

        prefix_hash = self.hash_prefix(static_items)

        # Determine if we hit the cache
        cache_hit = False
        cacheable_tokens = 0
        if static_tokens >= self.min_prefix:
            if prefix_hash in self.history_hashes:
                cache_hit = True
                cacheable_tokens = static_tokens
            else:
                # First time seeing this prefix, it writes to cache but doesn't read
                self.history_hashes.add(prefix_hash)

        # Cost math (Simulated Claude 3.5 Sonnet)
        # Base input: $3.00 / 1M tokens
        # Cache read: $0.30 / 1M tokens (90% off)
        # Cache write: $3.75 / 1M tokens (25% premium)

        if cache_hit:
            input_cost = (cacheable_tokens / 1_000_000) * 0.30 + (
                volatile_tokens / 1_000_000
            ) * 3.00
        else:
            if static_tokens >= self.min_prefix:
                input_cost = (static_tokens / 1_000_000) * 3.75 + (
                    volatile_tokens / 1_000_000
                ) * 3.00
            else:
                input_cost = (total_tokens / 1_000_000) * 3.00

        # Theoretical Latency (Time to First Token)
        # 100ms base + 10ms per 1k volatile tokens. Cache reads are near instant.
        latency_ms = 100 + ((total_tokens - cacheable_tokens) / 1000) * 10

        return {
            "total_tokens": total_tokens,
            "cache_hit": cache_hit,
            "cacheable_tokens": cacheable_tokens,
            "cost": input_cost,
            "latency_ms": latency_ms,
        }


# --- The Simulation ---


def run_simulation():
    print("=== Predictive Packer Proof of Concept ===\n")

    # 1. Base Setup
    system_prompt = ContextItem("system", "You are an agent...", 1200, "static")
    tools = ContextItem("tools", "read_file, list_dir", 800, "static")

    print("Scenario: Agent lists a directory, then reads the main file.")
    print("Tokens: System (1200), Tools (800), Main File (3000)\n")

    # --- REACTIVE PIPELINE ---
    print("--- 1. Reactive Pipeline (Current) ---")
    reactive_sim = CacheTopologySimulator()

    # Turn 1: List Directory
    t1_query = ContextItem("q1", "List dir", 20, "request")
    t1_result = ContextItem("r1", "Files: main.ts, utils.ts", 50, "volatile")

    res1 = reactive_sim.evaluate_pack([system_prompt, tools], [t1_query, t1_result])
    print(
        f"Turn 1 (List):  Cache Hit: {res1['cache_hit']}, Cost: ${res1['cost']:.6f}, Latency: {res1['latency_ms']:.0f}ms"
    )

    # Turn 2: Read File (Agent decides to read main.ts based on list)
    t2_query = ContextItem("q2", "Read main.ts", 20, "request")
    main_ts = ContextItem(
        "main.ts", "content...", 3000, "volatile"
    )  # Fetched and packed reactively

    res2 = reactive_sim.evaluate_pack([system_prompt, tools], [t2_query, main_ts])
    print(
        f"Turn 2 (Read):  Cache Hit: {res2['cache_hit']}, Cost: ${res2['cost']:.6f}, Latency: {res2['latency_ms']:.0f}ms"
    )
    print(f"Total Reactive Cost: ${(res1['cost'] + res2['cost']):.6f}")

    print("\n--- 2. Predictive Pipeline (Proposed) ---")
    predictive_sim = CacheTopologySimulator()

    # Turn 1: List Directory
    # The Predictive Packer notices 'list dir', predicts 'main.ts' will be read next,
    # fetches it in the background, and places it into the STATIC block to "warm" it.
    t1_query = ContextItem("q1", "List dir", 20, "request")
    t1_result = ContextItem("r1", "Files: main.ts, utils.ts", 50, "volatile")
    main_ts_predicted = ContextItem(
        "main.ts", "content...", 3000, "static"
    )  # Pushed to static prefix!

    pres1 = predictive_sim.evaluate_pack(
        [system_prompt, tools, main_ts_predicted], [t1_query, t1_result]
    )
    print(
        f"Turn 1 (List + Warm Cache): Cache Hit: {pres1['cache_hit']}, Cost: ${pres1['cost']:.6f}, Latency: {pres1['latency_ms']:.0f}ms"
    )

    # Turn 2: Read File
    # The agent explicitly requests it. It's already in the static prefix!
    t2_query = ContextItem("q2", "Read main.ts", 20, "request")

    pres2 = predictive_sim.evaluate_pack([system_prompt, tools, main_ts_predicted], [t2_query])
    print(
        f"Turn 2 (Read): Cache Hit: {pres2['cache_hit']}, Cost: ${pres2['cost']:.6f}, Latency: {pres2['latency_ms']:.0f}ms"
    )
    print(f"Total Predictive Cost: ${(pres1['cost'] + pres2['cost']):.6f}")

    print(
        f"\nCost Savings: {(((res1['cost'] + res2['cost']) - (pres1['cost'] + pres2['cost'])) / (res1['cost'] + res2['cost']) * 100):.1f}%"
    )
    print(
        f"Turn 2 Latency Reduction: {((res2['latency_ms'] - pres2['latency_ms']) / res2['latency_ms'] * 100):.1f}%"
    )


if __name__ == "__main__":
    run_simulation()
