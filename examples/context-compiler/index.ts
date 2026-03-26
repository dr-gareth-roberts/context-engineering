/**
 * Context Compiler — Declarative Context Compilation
 *
 * Demonstrates how to declare a context program with named slots, constraints,
 * and per-model optimisation targets instead of manually packing items.
 *
 * The compiler:
 *   1. Assigns items to declared slots by kind
 *   2. Applies per-slot strategies (priority, recency, relevance)
 *   3. Enforces constraints (coverage, freshness, budget utilisation)
 *   4. Runs model-specific optimisation passes (Claude, GPT-4, Gemini)
 *   5. Reports diagnostics, slot breakdowns, and quality metrics
 *
 * Think of it like a C compiler targeting different CPU architectures —
 * you declare what you want, and the compiler arranges it optimally for
 * each model's attention patterns.
 *
 * No API keys needed — everything runs locally with mock data.
 * Run: npx tsx examples/context-compiler/index.ts
 */

import type { ContextItem } from "@context-engineering/core";
import {
  createContextCompiler,
  contextProgram,
} from "@context-engineering/compiler";
import type {
  CompileResult,
  CompileDiagnostic,
  Slot,
} from "@context-engineering/compiler";

// ─── Formatting Helpers ─────────────────────────────────────────────

const RESET = "\x1b[0m";
const BOLD = "\x1b[1m";
const DIM = "\x1b[2m";
const GREEN = "\x1b[32m";
const YELLOW = "\x1b[33m";
const CYAN = "\x1b[36m";
const RED = "\x1b[31m";
const MAGENTA = "\x1b[35m";
const WHITE = "\x1b[37m";

function header(text: string): void {
  const line = "\u2500".repeat(60);
  console.log(`\n${CYAN}${line}${RESET}`);
  console.log(`${BOLD}${WHITE}  ${text}${RESET}`);
  console.log(`${CYAN}${line}${RESET}\n`);
}

function subheader(text: string): void {
  console.log(`\n${BOLD}${YELLOW}  ${text}${RESET}`);
  console.log(`${DIM}  ${"\u2500".repeat(text.length + 2)}${RESET}`);
}

function metric(label: string, value: string | number, color = WHITE): void {
  console.log(`  ${DIM}${label}:${RESET} ${color}${value}${RESET}`);
}

function bar(ratio: number, width = 30): string {
  const clamped = Math.max(0, Math.min(1, ratio));
  const filled = Math.round(clamped * width);
  const empty = width - filled;
  const colour = clamped > 0.7 ? GREEN : clamped > 0.4 ? YELLOW : RED;
  return `${colour}${"█".repeat(filled)}${DIM}${"░".repeat(empty)}${RESET}`;
}

function diagIcon(level: string): string {
  if (level === "error") return `${RED}[ERR]${RESET}`;
  if (level === "warning") return `${YELLOW}[WRN]${RESET}`;
  return `${DIM}[INF]${RESET}`;
}

// ─── Mock Data ──────────────────────────────────────────────────────
// A realistic set of context items for a code-review assistant.

function makeItem(
  id: string,
  content: string,
  overrides: Partial<ContextItem>
): ContextItem {
  return {
    id,
    content,
    tokens: Math.ceil(content.split(/\s+/).length * 1.3),
    ...overrides,
  };
}

const systemPrompt = makeItem(
  "sys-prompt",
  "You are a senior software engineer conducting a thorough code review. " +
    "Focus on correctness, security, performance, and maintainability. " +
    "Flag any potential issues with clear severity ratings. " +
    "Suggest concrete improvements with code examples where appropriate.",
  { kind: "system", priority: 10 }
);

const codeItems: ContextItem[] = [
  makeItem(
    "pr-diff-auth",
    "diff --git a/src/auth.ts b/src/auth.ts\n" +
      "+export async function verifyToken(token: string): Promise<User> {\n" +
      "+  const decoded = jwt.verify(token, process.env.JWT_SECRET!);\n" +
      "+  const user = await db.users.findUnique({ where: { id: decoded.sub } });\n" +
      "+  if (!user) throw new AuthError('User not found');\n" +
      "+  return user;\n" +
      "+}",
    { kind: "code", priority: 9, recency: 10 }
  ),
  makeItem(
    "pr-diff-middleware",
    "diff --git a/src/middleware.ts b/src/middleware.ts\n" +
      "+export function rateLimiter(max: number, windowMs: number) {\n" +
      "+  const store = new Map<string, number[]>();\n" +
      "+  return (req: Request, res: Response, next: NextFunction) => {\n" +
      "+    const key = req.ip;\n" +
      "+    const now = Date.now();\n" +
      "+    const hits = (store.get(key) ?? []).filter(t => t > now - windowMs);\n" +
      "+    hits.push(now);\n" +
      "+    store.set(key, hits);\n" +
      "+    if (hits.length > max) return res.status(429).json({ error: 'Rate limited' });\n" +
      "+    next();\n" +
      "+  };\n" +
      "+}",
    { kind: "code", priority: 8, recency: 9 }
  ),
  makeItem(
    "pr-diff-utils",
    "diff --git a/src/utils.ts b/src/utils.ts\n" +
      "+export function slugify(text: string): string {\n" +
      "+  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');\n" +
      "+}\n" +
      "+export function truncate(s: string, len: number): string {\n" +
      "+  return s.length > len ? s.slice(0, len) + '...' : s;\n" +
      "+}",
    { kind: "code", priority: 5, recency: 8 }
  ),
  makeItem(
    "pr-diff-db",
    "diff --git a/src/db.ts b/src/db.ts\n" +
      "+export const prisma = new PrismaClient({ log: ['query', 'error'] });\n" +
      "+export async function healthCheck(): Promise<boolean> {\n" +
      "+  try { await prisma.$queryRaw`SELECT 1`; return true; }\n" +
      "+  catch { return false; }\n" +
      "+}",
    { kind: "code", priority: 6, recency: 7 }
  ),
];

const docItems: ContextItem[] = [
  makeItem(
    "doc-jwt",
    "JWT Best Practices: Always validate the algorithm header. Use short expiry " +
      "times (15 minutes for access tokens). Store refresh tokens securely. " +
      "Never put sensitive data in the payload — it is base64-encoded, not encrypted.",
    { kind: "docs", priority: 7, recency: 4, score: 0.9 }
  ),
  makeItem(
    "doc-rate-limit",
    "Rate Limiting Patterns: Use sliding window counters for accuracy. " +
      "Store state in Redis for distributed systems. Consider using token bucket " +
      "for bursty traffic. Always return Retry-After headers with 429 responses.",
    { kind: "docs", priority: 6, recency: 3, score: 0.8 }
  ),
  makeItem(
    "doc-prisma",
    "Prisma Performance Guide: Use select/include to avoid over-fetching. " +
      "Enable query logging in development only. Use connection pooling in production " +
      "(PgBouncer or Prisma Accelerate). Batch writes with createMany when possible.",
    { kind: "docs", priority: 5, recency: 2, score: 0.7 }
  ),
  makeItem(
    "doc-testing",
    "Testing Guidelines: Unit test pure functions, integration test API endpoints. " +
      "Mock external services at the boundary. Use factories for test data. " +
      "Aim for behaviour coverage over line coverage.",
    { kind: "docs", priority: 3, recency: 1, score: 0.4 }
  ),
];

const historyItems: ContextItem[] = [
  makeItem(
    "hist-1",
    "User: Can you review this PR? It adds authentication and rate limiting.",
    { kind: "history", priority: 4, recency: 10 }
  ),
  makeItem(
    "hist-2",
    "Assistant: I'll review the PR focusing on security, performance, and correctness. " +
      "Let me start with the authentication module.",
    { kind: "history", priority: 3, recency: 9 }
  ),
  makeItem(
    "hist-3",
    "User: Please pay extra attention to the JWT handling — we had a vulnerability last quarter.",
    { kind: "history", priority: 6, recency: 8 }
  ),
];

const allItems = [systemPrompt, ...codeItems, ...docItems, ...historyItems];

// ─── Helper: Print Compilation Result ───────────────────────────────

function printResult(result: CompileResult, label: string): void {
  subheader(`${label} (target: ${result.target})`);

  // Slot breakdown
  console.log();
  const slotNames = Object.keys(result.slots);
  const maxNameLen = Math.max(...slotNames.map(n => n.length), 4);
  console.log(
    `  ${DIM}${"Slot".padEnd(maxNameLen)}  Items  Tokens  Filled${RESET}`
  );
  for (const name of slotNames) {
    const slot = result.slots[name];
    const pct =
      result.totalTokens > 0 ? slot.tokensUsed / result.totalTokens : 0;
    const satisfied = slot.satisfied
      ? `${GREEN}yes${RESET}`
      : `${RED}NO${RESET}`;
    console.log(
      `  ${WHITE}${name.padEnd(maxNameLen)}${RESET}  ` +
        `${String(slot.itemCount).padStart(5)}  ` +
        `${String(slot.tokensUsed).padStart(6)}  ` +
        `${satisfied}`
    );
  }

  // Budget usage
  console.log();
  metric("Selected", `${result.items.length} items`);
  metric("Dropped", `${result.dropped.length} items`);
  metric("Tokens used", result.totalTokens);
  console.log(
    `  ${DIM}Budget:${RESET}  ${bar(result.totalTokens / 1000)} ${(result.totalTokens / 10).toFixed(1)}%`
  );

  // Quality
  console.log();
  metric(
    "Overall quality",
    `${(result.quality.overall * 100).toFixed(1)}%`,
    GREEN
  );
  metric("Item count", result.quality.itemCount);

  // Optimisations applied
  if (result.optimizations.length > 0) {
    console.log();
    console.log(`  ${DIM}Optimisations:${RESET}`);
    for (const opt of result.optimizations) {
      console.log(`    ${MAGENTA}${opt.name}${RESET} — ${opt.description}`);
      console.log(
        `      ${DIM}${opt.itemsReordered} items reordered, ${opt.tokensAffected} tokens affected${RESET}`
      );
    }
  }

  // Diagnostics
  const diags = result.diagnostics;
  if (diags.length > 0) {
    console.log();
    console.log(`  ${DIM}Diagnostics (${diags.length}):${RESET}`);
    for (const d of diags) {
      const scope = d.slot
        ? ` [${d.slot}]`
        : d.constraint
          ? ` [${d.constraint}]`
          : "";
      console.log(`    ${diagIcon(d.level)}${scope} ${d.message}`);
    }
  }
}

// ─── 1. Define the Context Program ──────────────────────────────────

header("1. Define Context Program");

console.log("  Declaring slots with position constraints and strategies:");
console.log(
  `    ${CYAN}system${RESET}  — required, pinned first, max 200 tokens`
);
console.log(
  `    ${CYAN}code${RESET}    — highest-priority diffs, max 600 tokens`
);
console.log(
  `    ${CYAN}docs${RESET}    — most-relevant reference docs, max 300 tokens`
);
console.log(
  `    ${CYAN}history${RESET} — most-recent conversation, pinned last`
);
console.log(
  `    ${CYAN}extra${RESET}   — anything that fits in leftover budget`
);

const program = contextProgram()
  .declare("system", {
    kind: "system",
    required: true,
    position: "first",
    maxTokens: 200,
  })
  .declare("code", {
    kind: "code",
    strategy: "priority",
    maxTokens: 600,
  })
  .declare("docs", {
    kind: "docs",
    strategy: "relevance",
    maxTokens: 300,
  })
  .declare("history", {
    kind: "history",
    strategy: "recency",
    position: "last",
  })
  .declare("extra", {
    kind: "extra",
    fillRemaining: true,
  })
  .constraint("coverage")
  .constraint("budget-utilization", { threshold: 0.5 })
  .constraint("freshness", { threshold: 0.3 })
  .build();

console.log(
  `\n  ${GREEN}Program built:${RESET} ${program.slots.length} slots, ${program.constraints.length} constraints`
);

// ─── 2. Compile for Claude ──────────────────────────────────────────

header("2. Compile for Claude");

console.log(
  "  Claude places high-priority content at the start and end of the"
);
console.log(
  "  context window (primacy/recency bias). The compiler reorders items"
);
console.log("  to take advantage of this attention pattern.\n");

const compiler = createContextCompiler();

const claudeResult = compiler.compile(program, {
  target: "claude",
  items: allItems,
  budget: { maxTokens: 1000 },
});

printResult(claudeResult, "Claude compilation");

// ─── 3. Compile for GPT-4 ──────────────────────────────────────────

header("3. Compile for GPT-4");

console.log(
  "  GPT-4 attends more uniformly but benefits from logical grouping."
);
console.log(
  "  The compiler clusters related items and uses different ordering.\n"
);

const gptResult = compiler.compile(program, {
  target: "gpt4",
  items: allItems,
  budget: { maxTokens: 1000 },
});

printResult(gptResult, "GPT-4 compilation");

// ─── 4. Compare Item Order ──────────────────────────────────────────

header("4. Compare Item Ordering Across Models");

const claudeIds = claudeResult.items.map(i => i.id);
const gptIds = gptResult.items.map(i => i.id);

console.log(`  ${CYAN}Claude order:${RESET}`);
claudeIds.forEach((id, i) =>
  console.log(`    ${DIM}${String(i + 1).padStart(2)}.${RESET} ${id}`)
);
console.log();
console.log(`  ${YELLOW}GPT-4 order:${RESET}`);
gptIds.forEach((id, i) =>
  console.log(`    ${DIM}${String(i + 1).padStart(2)}.${RESET} ${id}`)
);

const sameOrder = claudeIds.every((id, i) => id === gptIds[i]);
console.log(
  `\n  ${sameOrder ? `${YELLOW}Same ordering` : `${GREEN}Different ordering`} — ` +
    `model-specific optimisation ${sameOrder ? "not needed" : "applied"}${RESET}`
);

// ─── 5. Compile Under Tight Budget ─────────────────────────────────

header("5. Tight Budget — Required Slots and Diagnostics");

console.log(
  "  With only 300 tokens, the compiler must prioritise required slots"
);
console.log("  and report what couldn't fit.\n");

const tightResult = compiler.compile(program, {
  target: "generic",
  items: allItems,
  budget: { maxTokens: 300 },
});

printResult(tightResult, "Tight budget (300 tokens)");

// Show what was dropped
if (tightResult.dropped.length > 0) {
  console.log();
  console.log(`  ${DIM}Dropped items:${RESET}`);
  for (const d of tightResult.dropped) {
    console.log(`    ${RED}-${RESET} ${d.id} (${d.kind}, ${d.tokens} tokens)`);
  }
}

// ─── 6. Missing Required Slot ───────────────────────────────────────

header("6. Missing Required Slot — Error Diagnostics");

console.log(
  "  If we compile without any system-kind items, the compiler reports"
);
console.log("  an error diagnostic for the unsatisfied required slot.\n");

const noSystemItems = allItems.filter(i => i.kind !== "system");
const missingResult = compiler.compile(program, {
  target: "generic",
  items: noSystemItems,
  budget: { maxTokens: 1000 },
});

const errors = missingResult.diagnostics.filter(d => d.level === "error");
const warnings = missingResult.diagnostics.filter(d => d.level === "warning");
const infos = missingResult.diagnostics.filter(d => d.level === "info");

console.log(`  ${RED}Errors:   ${errors.length}${RESET}`);
console.log(`  ${YELLOW}Warnings: ${warnings.length}${RESET}`);
console.log(`  ${DIM}Info:     ${infos.length}${RESET}`);
console.log();
for (const d of errors) {
  console.log(`  ${RED}[ERR]${RESET} ${d.message}`);
}
console.log(
  `\n  ${DIM}This lets you catch misconfigured pipelines before sending to the model.${RESET}`
);

// ─── Summary ────────────────────────────────────────────────────────

header("Summary");

console.log("  The Context Compiler lets you:");
console.log(
  `    ${GREEN}1.${RESET} Declare named slots with position, budget, and strategy constraints`
);
console.log(
  `    ${GREEN}2.${RESET} Compile the same items for different model targets`
);
console.log(
  `    ${GREEN}3.${RESET} Get per-slot breakdowns showing what filled each slot`
);
console.log(
  `    ${GREEN}4.${RESET} Receive actionable diagnostics when constraints are violated`
);
console.log(
  `    ${GREEN}5.${RESET} Automatically reorder items for each model's attention pattern`
);
console.log();
console.log(
  `  ${DIM}See docs/wiki/Context-Compilation.md for the full guide.${RESET}\n`
);
