# Pricing (Claude 3.5 Sonnet) per 1M tokens
BASE_COST = 3.00
CACHE_WRITE_COST = 3.75
CACHE_READ_COST = 0.30

# Scenario Setup
SYSTEM_TOKENS = 2000
FILE_1_TOKENS = 4000
FILE_2_TOKENS = 3000
FILE_3_TOKENS = 5000
TOTAL_FILE_TOKENS = FILE_1_TOKENS + FILE_2_TOKENS + FILE_3_TOKENS

print("=== Asynchronous Shadow Warming Proof ===")
print(
    "Scenario: Agent searches a codebase. Over the next 3 turns, it reads File 1, File 2, and File 3."
)
print(
    f"Tokens: System ({SYSTEM_TOKENS}), File 1 ({FILE_1_TOKENS}), File 2 ({FILE_2_TOKENS}), File 3 ({FILE_3_TOKENS})\n"
)

# ---------------------------------------------------------
# 1. Reactive Approach (Current Standard)
# The system prefix is cached, but each file is added dynamically as a volatile item.
# ---------------------------------------------------------
print("--- 1. Reactive Approach ---")
# Turn 0: Initial cache write for the system prompt
r_t0_cost = (SYSTEM_TOKENS / 1_000_000) * CACHE_WRITE_COST

# Turn 1: Read File 1 (System is cache hit, File 1 is base cost)
r_t1_cost = (SYSTEM_TOKENS / 1_000_000) * CACHE_READ_COST + (FILE_1_TOKENS / 1_000_000) * BASE_COST

# Turn 2: Read File 2
r_t2_cost = (SYSTEM_TOKENS / 1_000_000) * CACHE_READ_COST + (FILE_2_TOKENS / 1_000_000) * BASE_COST

# Turn 3: Read File 3
r_t3_cost = (SYSTEM_TOKENS / 1_000_000) * CACHE_READ_COST + (FILE_3_TOKENS / 1_000_000) * BASE_COST

reactive_total = r_t0_cost + r_t1_cost + r_t2_cost + r_t3_cost
print(f"Initial System Cache Write: ${r_t0_cost:.6f}")
print(f"Turn 1 (Read File 1):       ${r_t1_cost:.6f}")
print(f"Turn 2 (Read File 2):       ${r_t2_cost:.6f}")
print(f"Turn 3 (Read File 3):       ${r_t3_cost:.6f}")
print(f"Total Reactive Cost:        ${reactive_total:.6f}\n")


# ---------------------------------------------------------
# 2. Predictive Shadow Warming Approach
# Background process predicts the 3 files, writes them to cache ONCE.
# The agent then gets a cache hit for EVERYTHING over the next 3 turns.
# ---------------------------------------------------------
print("--- 2. Predictive Shadow Warming ---")

# The Shadow Request: Sent asynchronously after the search.
# It writes the System + All 3 Files into the cache prefix.
shadow_tokens = SYSTEM_TOKENS + TOTAL_FILE_TOKENS
shadow_write_cost = (shadow_tokens / 1_000_000) * CACHE_WRITE_COST

# Turn 1: Agent requests File 1.
# The Predictive Packer gives the API the exact same prefix (System + All 3 Files).
# The API sees a 100% cache hit. The LLM only attends to File 1 based on the prompt.
p_t1_cost = (shadow_tokens / 1_000_000) * CACHE_READ_COST

# Turn 2: Agent requests File 2. 100% cache hit again.
p_t2_cost = (shadow_tokens / 1_000_000) * CACHE_READ_COST

# Turn 3: Agent requests File 3. 100% cache hit again.
p_t3_cost = (shadow_tokens / 1_000_000) * CACHE_READ_COST

predictive_total = shadow_write_cost + p_t1_cost + p_t2_cost + p_t3_cost
print(f"Background Shadow Write:    ${shadow_write_cost:.6f} (Paid implicitly in background)")
print(f"Turn 1 (Read File 1):       ${p_t1_cost:.6f}")
print(f"Turn 2 (Read File 2):       ${p_t2_cost:.6f}")
print(f"Turn 3 (Read File 3):       ${p_t3_cost:.6f}")
print(f"Total Predictive Cost:      ${predictive_total:.6f}\n")

# ---------------------------------------------------------
# Results
# ---------------------------------------------------------
savings = reactive_total - predictive_total
percent_saved = (savings / reactive_total) * 100

print("=== Conclusion ===")
print(f"Reactive Total:   ${reactive_total:.6f}")
print(f"Predictive Total: ${predictive_total:.6f}")
print(f"Total Savings:    ${savings:.6f} ({percent_saved:.1f}% cost reduction)")

# Latency Impact (Time to First Token)
# Assuming 10ms per 1k input tokens, cache hits are near 0ms.
r_t1_latency = (FILE_1_TOKENS / 1000) * 10
p_t1_latency = 0  # Cache hit
print("\nUser-Facing Latency (Turn 1):")
print(f"Reactive:   {r_t1_latency:.0f}ms blocking the user")
print("Predictive: 0ms blocking the user (warmed in background)")
