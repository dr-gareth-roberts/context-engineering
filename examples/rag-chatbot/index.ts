/**
 * RAG Chatbot — Context Engineering Example
 *
 * Demonstrates a complete retrieval-augmented generation loop:
 *   1. In-memory vector store with sample API documentation
 *   2. Context-aware retrieval with information-gain filtering
 *   3. Pipeline packing with budget allocation across kinds
 *   4. Cache topology optimization for prefix reuse
 *   5. Quality gate analysis
 *   6. Graceful degradation under a tight budget
 *
 * No API keys needed — everything runs locally with mock data.
 * Run: npx tsx examples/rag-chatbot/index.ts
 */

import { pipeline, estimateTokens } from "@context-engineering/core";
import type { ContextItem, KindAllocation } from "@context-engineering/core";
import { createContextAwareRetriever } from "@context-engineering/rag";
import type { VectorStoreLike, VectorResult } from "@context-engineering/rag";

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
  const color = clamped > 0.7 ? GREEN : clamped > 0.4 ? YELLOW : RED;
  return `${color}${"\u2588".repeat(filled)}${DIM}${"\u2591".repeat(empty)}${RESET}`;
}

// ─── 1. Sample Documents ────────────────────────────────────────────
// Realistic API documentation for a fictional "Acme API" service.
// Each document covers a distinct topic to demonstrate information-gain scoring.

const documents: Array<{ id: string; content: string; topic: string }> = [
  {
    id: "doc-auth-overview",
    topic: "authentication",
    content: `Authentication Overview
All Acme API requests require a Bearer token in the Authorization header.
Tokens are obtained via POST /oauth/token with your client_id and client_secret.
Access tokens expire after 3600 seconds. Use the refresh_token grant to renew
without re-authenticating. Scopes control access: read, write, admin.`,
  },
  {
    id: "doc-auth-mfa",
    topic: "authentication",
    content: `Multi-Factor Authentication
For admin-scoped tokens, MFA is required. After initial authentication,
the server returns a 403 with an mfa_challenge_id. Complete the challenge
via POST /oauth/mfa with the TOTP code from your authenticator app.
MFA sessions persist for 24 hours per device fingerprint.`,
  },
  {
    id: "doc-rate-limits",
    topic: "rate-limits",
    content: `Rate Limiting
The Acme API enforces tiered rate limits based on your plan:
- Free: 60 requests/minute, 1000 requests/day
- Pro: 600 requests/minute, 50,000 requests/day
- Enterprise: 6000 requests/minute, unlimited daily
Rate limit headers are included in every response:
X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset (Unix epoch).
When exceeded, the API returns 429 Too Many Requests with a Retry-After header.`,
  },
  {
    id: "doc-rate-limit-retry",
    topic: "rate-limits",
    content: `Rate Limit Retry Strategies
Implement exponential backoff with jitter when receiving 429 responses.
Start with a base delay of 1 second, doubling each retry up to 32 seconds.
Add random jitter of 0-500ms to prevent thundering herd.
Use the Retry-After header value when present \u2014 it gives the exact wait time.
Client SDKs handle this automatically with configurable max retries (default: 3).`,
  },
  {
    id: "doc-endpoints-users",
    topic: "endpoints",
    content: `Users API
GET /v2/users \u2014 List users (paginated, 50 per page)
GET /v2/users/:id \u2014 Get user by ID
POST /v2/users \u2014 Create user (requires write scope)
PATCH /v2/users/:id \u2014 Update user fields
DELETE /v2/users/:id \u2014 Soft-delete user (requires admin scope)
All responses use JSON:API format with included relationships.`,
  },
  {
    id: "doc-endpoints-projects",
    topic: "endpoints",
    content: `Projects API
GET /v2/projects \u2014 List projects (filterable by status, owner)
POST /v2/projects \u2014 Create project with name, description, team_id
PATCH /v2/projects/:id \u2014 Update project metadata
POST /v2/projects/:id/archive \u2014 Archive a project (reversible)
Projects support nested resources: /v2/projects/:id/tasks, /v2/projects/:id/members.`,
  },
  {
    id: "doc-errors",
    topic: "errors",
    content: `Error Handling
All errors follow RFC 7807 Problem Details format:
{ "type": "https://api.acme.io/errors/validation",
  "title": "Validation Error", "status": 422,
  "detail": "Field 'email' must be a valid email address",
  "errors": [{ "field": "email", "code": "invalid_format" }] }
Common status codes: 400 (bad request), 401 (unauthorized), 403 (forbidden),
404 (not found), 409 (conflict), 422 (validation), 429 (rate limited), 500 (server error).`,
  },
  {
    id: "doc-versioning",
    topic: "versioning",
    content: `API Versioning
The Acme API uses URL path versioning: /v1/, /v2/, etc.
The current version is v2. Version v1 is deprecated and will be removed 2025-12-31.
Breaking changes are only introduced in new major versions.
Non-breaking additions (new fields, new endpoints) happen in minor releases
and are announced in the changelog at https://api.acme.io/changelog.`,
  },
  {
    id: "doc-pagination",
    topic: "pagination",
    content: `Pagination
List endpoints use cursor-based pagination for consistent results.
Pass ?cursor=<value>&limit=50 to paginate. The response includes:
{ "data": [...], "meta": { "cursor": "abc123", "has_more": true } }
Maximum limit is 100 items per page. Omit cursor for the first page.
Cursors are opaque strings \u2014 do not parse or construct them.`,
  },
  {
    id: "doc-webhooks",
    topic: "webhooks",
    content: `Webhooks
Subscribe to events via POST /v2/webhooks with a target URL and event types.
Events: user.created, user.updated, project.created, project.archived.
Webhook payloads are signed with HMAC-SHA256 using your webhook secret.
Verify signatures by comparing the X-Acme-Signature header.
Failed deliveries are retried 5 times with exponential backoff over 24 hours.`,
  },
];

// ─── 2. Mock Vector Store ───────────────────────────────────────────
// Simulates a vector database by scoring documents based on keyword overlap
// with the query. In production, you would use Pinecone, Chroma, pgvector, etc.

function createMockVectorStore(): VectorStoreLike {
  return {
    async query(text: string, topK: number): Promise<VectorResult[]> {
      const queryTerms = text.toLowerCase().split(/\s+/);

      const scored = documents.map(doc => {
        const contentLower = doc.content.toLowerCase();
        const topicLower = doc.topic.toLowerCase();

        // Score based on term overlap -- crude but effective for demo
        let score = 0;
        for (const term of queryTerms) {
          if (term.length < 3) continue;
          // Topic match is a strong signal
          if (topicLower.includes(term)) score += 0.3;
          // Count content occurrences (diminishing returns)
          const matches = contentLower.split(term).length - 1;
          score += Math.min(matches * 0.1, 0.4);
        }

        // Normalize to 0-1 range
        score = Math.min(score / 1.5, 1.0);

        return {
          id: doc.id,
          content: doc.content,
          score,
          metadata: { topic: doc.topic },
        };
      });

      return scored.sort((a, b) => b.score - a.score).slice(0, topK);
    },
  };
}

// ─── 3. System Prompt & Conversation History ────────────────────────
// These represent the non-retrieval parts of the context window.

const systemPrompt: ContextItem = {
  id: "system-prompt",
  content: `You are a helpful API support assistant for the Acme API.
Answer questions accurately using the provided documentation.
If the documentation doesn't cover a topic, say so rather than guessing.
Always include relevant code examples in your responses.
Format responses in Markdown.`,
  kind: "system",
  priority: 10,
  recency: 1,
};

const conversationHistory: ContextItem[] = [
  {
    id: "msg-1-user",
    content:
      "User: I'm building a Node.js app that needs to call your API. Where do I start?",
    kind: "conversation",
    priority: 5,
    recency: 6,
  },
  {
    id: "msg-2-assistant",
    content:
      "Assistant: Start by obtaining API credentials from the developer dashboard. You'll need a client_id and client_secret to authenticate. I can walk you through the auth flow next.",
    kind: "conversation",
    priority: 5,
    recency: 7,
  },
  {
    id: "msg-3-user",
    content: "User: Great, and how do I authenticate and handle rate limits?",
    kind: "conversation",
    priority: 7,
    recency: 9,
  },
];

// ─── 4. Retrieval with Information Gain ─────────────────────────────
// The retriever scores candidates against existing context to avoid
// wasting budget on redundant chunks. Only genuinely novel + relevant
// information makes it through.

async function runRetrieval(query: string, budgetTokens: number) {
  const store = createMockVectorStore();

  // The retriever needs to know what is already in the context
  // so it can compute information gain (novelty vs. redundancy)
  const existingContext: ContextItem[] = [systemPrompt, ...conversationHistory];

  const retriever = createContextAwareRetriever({
    store,
    currentContext: existingContext,
    budget: { maxTokens: budgetTokens, reserveTokens: 200 },
    maxCandidates: 30,
  });

  const retrieved = await retriever.retrieve(query, {
    topK: 10,
    minGain: 0.15, // Filter out low-information chunks
    query: {
      text: query,
      keywords: ["authenticate", "rate", "limit", "token", "bearer"],
    },
  });

  return retrieved;
}

// ─── 5. Pipeline Packing ────────────────────────────────────────────
// Combines system prompt, retrieved docs, and conversation into a
// budget-aware context window with allocation, caching, and quality.

function runPipeline(
  retrievedItems: ContextItem[],
  budgetTokens: number,
  allocations: KindAllocation[]
) {
  return pipeline({ maxTokens: budgetTokens, reserveTokens: 200 })
    .add(systemPrompt)
    .addMany(retrievedItems, { kind: "retrieval" })
    .addMany(conversationHistory)
    .allocate(allocations)
    .cacheTopology({ provider: "anthropic" })
    .qualityGate({ minOverall: 0.3 })
    .build();
}

// ─── 6. Report Formatting ───────────────────────────────────────────

function printRetrievalReport(
  retrieved: Awaited<ReturnType<typeof runRetrieval>>
) {
  subheader("Retrieval Results");
  metric("Candidates evaluated", retrieved.candidatesEvaluated);
  metric("Candidates filtered (low gain)", retrieved.candidatesFiltered, RED);
  metric("Items selected", retrieved.items.length, GREEN);
  metric("Tokens used", retrieved.tokensUsed);
  metric("Total information gain", retrieved.totalGain.toFixed(3), MAGENTA);

  console.log();
  console.log(
    `  ${DIM}${"ID".padEnd(25)} ${"Topic".padEnd(15)} ${"Tokens".padStart(6)} ${"Vector".padStart(8)} Gain${RESET}`
  );
  console.log(`  ${DIM}${"\u2500".repeat(65)}${RESET}`);

  for (const item of retrieved.items) {
    const vectorScore = ((item.metadata?.vectorScore as number) ?? 0).toFixed(
      3
    );
    const tokens = estimateTokens(item.content);
    const topic = (item.metadata?.topic as string) ?? "unknown";
    console.log(
      `  ${WHITE}${item.id.padEnd(25)}${RESET} ${CYAN}${topic.padEnd(15)}${RESET} ${tokens.toString().padStart(6)} ${YELLOW}${vectorScore.padStart(8)}${RESET} ${GREEN}${bar(parseFloat(vectorScore), 15)}${RESET}`
    );
  }
}

function printPipelineReport(
  result: ReturnType<typeof runPipeline>,
  label: string,
  budgetTokens: number
) {
  subheader(`Pipeline: ${label}`);
  metric("Budget", `${budgetTokens} tokens`);
  metric("Input items", result.inputCount);
  metric(
    "Selected",
    `${result.selected.length} items (${result.totalTokens} tokens)`,
    GREEN
  );
  metric(
    "Dropped",
    `${result.dropped.length} items`,
    result.dropped.length > 0 ? RED : GREEN
  );
  metric("Stages", result.stages.join(" -> "), CYAN);

  // Budget utilization
  const utilization = result.totalTokens / budgetTokens;
  console.log(
    `\n  ${DIM}Utilization:${RESET} ${bar(utilization)} ${(utilization * 100).toFixed(1)}%`
  );

  // Selected items breakdown
  console.log(
    `\n  ${DIM}${"Kind".padEnd(15)} ${"ID".padEnd(25)} ${"Tokens".padStart(6)} ${"Score".padStart(7)}${RESET}`
  );
  console.log(`  ${DIM}${"\u2500".repeat(55)}${RESET}`);

  for (const item of result.selected) {
    const kind = item.kind ?? "unknown";
    const tokens = item.tokens ?? estimateTokens(item.content);
    const score = item.score?.toFixed(2) ?? "  -  ";
    console.log(
      `  ${CYAN}${kind.padEnd(15)}${RESET} ${WHITE}${item.id.padEnd(25)}${RESET} ${tokens.toString().padStart(6)} ${YELLOW}${score.toString().padStart(7)}${RESET}`
    );
  }

  // Dropped items
  if (result.dropped.length > 0) {
    console.log(`\n  ${RED}Dropped:${RESET}`);
    for (const item of result.dropped) {
      const kind = item.kind ?? "unknown";
      const tokens = item.tokens ?? estimateTokens(item.content);
      console.log(
        `  ${DIM}  x ${kind.padEnd(12)} ${item.id.padEnd(25)} (${tokens} tokens)${RESET}`
      );
    }
  }

  // Quality metrics
  if (result.quality) {
    const q = result.quality;
    console.log();
    subheader("Quality Metrics");
    console.log(
      `  ${DIM}Density:${RESET}    ${bar(q.density)} ${q.density.toFixed(3)}`
    );
    console.log(
      `  ${DIM}Diversity:${RESET}  ${bar(q.diversity)} ${q.diversity.toFixed(3)}`
    );
    console.log(
      `  ${DIM}Freshness:${RESET}  ${bar(q.freshness)} ${q.freshness.toFixed(3)}`
    );
    console.log(
      `  ${DIM}Redundancy:${RESET} ${bar(1 - q.redundancy)} ${q.redundancy.toFixed(3)} ${q.redundancy > 0.3 ? RED + "(high)" + RESET : GREEN + "(low)" + RESET}`
    );
    console.log(
      `  ${DIM}Overall:${RESET}    ${bar(q.overall)} ${BOLD}${q.overall >= 0.6 ? GREEN : YELLOW}${q.overall.toFixed(3)}${RESET}`
    );
  }

  // Cache topology
  if (result.cacheKey) {
    console.log();
    subheader("Cache Topology");
    metric("Cache key", result.cacheKey.slice(0, 16) + "...");
    metric(
      "Cacheable tokens",
      `${result.cacheableTokens} / ${result.totalTokens}`
    );
    const eff = result.cacheEfficiency ?? 0;
    console.log(
      `  ${DIM}Efficiency:${RESET} ${bar(eff)} ${(eff * 100).toFixed(1)}%`
    );
    console.log(
      `  ${DIM}Benefit:${RESET}    ${CYAN}Repeated calls with the same prefix save ~90% on input token cost${RESET}`
    );
  }

  // Allocation breakdown
  if (result.allocations) {
    console.log();
    subheader("Budget Allocation");
    const allocs = result.allocations as Record<
      string,
      {
        kind: string;
        budgetAllocated: number;
        budgetUsed: number;
        itemCount: number;
        surplus: number;
      }
    >;
    console.log(
      `  ${DIM}${"Kind".padEnd(15)} ${"Allocated".padStart(10)} ${"Used".padStart(8)} ${"Items".padStart(6)} ${"Surplus".padStart(8)}${RESET}`
    );
    console.log(`  ${DIM}${"\u2500".repeat(50)}${RESET}`);
    for (const [, alloc] of Object.entries(allocs)) {
      const usageRatio =
        alloc.budgetAllocated > 0
          ? alloc.budgetUsed / alloc.budgetAllocated
          : 0;
      const color = usageRatio > 0.8 ? GREEN : usageRatio > 0.4 ? YELLOW : RED;
      console.log(
        `  ${CYAN}${alloc.kind.padEnd(15)}${RESET} ${alloc.budgetAllocated.toString().padStart(10)} ${color}${alloc.budgetUsed.toString().padStart(8)}${RESET} ${alloc.itemCount.toString().padStart(6)} ${DIM}${alloc.surplus.toString().padStart(8)}${RESET}`
      );
    }
    metric(
      "\n  Allocation efficiency",
      `${((result.allocationEfficiency ?? 0) * 100).toFixed(1)}%`,
      result.allocationEfficiency! > 0.7 ? GREEN : YELLOW
    );
  }
}

// ─── 7. Main ────────────────────────────────────────────────────────

async function main() {
  header("RAG Chatbot \u2014 Context Engineering Demo");

  console.log(
    `${DIM}  This demo shows how context-engineering manages the retrieval ->
  pack -> deliver loop for a RAG chatbot, without making any LLM calls.
  The focus is on what goes INTO the context window and why.${RESET}`
  );

  const query = "How do I authenticate and handle rate limits?";
  console.log(`\n  ${BOLD}User query:${RESET} "${CYAN}${query}${RESET}"\n`);

  // -- Scenario 1: Comfortable budget (2000 tokens) --
  // Enough room for system prompt, conversation, and several docs.

  header("Scenario 1: Comfortable Budget (2000 tokens)");

  const largeBudget = 2000;
  const retrieved1 = await runRetrieval(query, largeBudget);
  printRetrievalReport(retrieved1);

  const allocations1: KindAllocation[] = [
    { kind: "system", targetRatio: 0.15, minTokens: 50, priority: 10 },
    { kind: "retrieval", targetRatio: 0.6, priority: 5 },
    { kind: "conversation", targetRatio: 0.25, priority: 7 },
  ];

  const result1 = runPipeline(retrieved1.items, largeBudget, allocations1);
  printPipelineReport(result1, "Comfortable Budget", largeBudget);

  // -- Scenario 2: Tight budget (600 tokens) --
  // Forces the pipeline to make hard choices about what to keep.

  header("Scenario 2: Tight Budget (600 tokens)");

  console.log(
    `${DIM}  Same query, same documents \u2014 but only 600 tokens to work with.
  Watch how the pipeline preserves the most important information
  while gracefully dropping lower-value content.${RESET}\n`
  );

  const smallBudget = 600;
  const retrieved2 = await runRetrieval(query, smallBudget);
  printRetrievalReport(retrieved2);

  const allocations2: KindAllocation[] = [
    { kind: "system", targetRatio: 0.2, minTokens: 40, priority: 10 },
    { kind: "retrieval", targetRatio: 0.55, priority: 5 },
    { kind: "conversation", targetRatio: 0.25, priority: 7 },
  ];

  const result2 = runPipeline(retrieved2.items, smallBudget, allocations2);
  printPipelineReport(result2, "Tight Budget", smallBudget);

  // -- Comparison --

  header("Comparison: Budget Impact");

  const q1 = result1.quality;
  const q2 = result2.quality;

  console.log(
    `  ${DIM}${"Metric".padEnd(22)} ${"2000 tokens".padStart(14)} ${"600 tokens".padStart(14)} ${"Delta".padStart(10)}${RESET}`
  );
  console.log(`  ${DIM}${"\u2500".repeat(62)}${RESET}`);

  const rows: Array<[string, number | undefined, number | undefined]> = [
    ["Items selected", result1.selected.length, result2.selected.length],
    ["Tokens used", result1.totalTokens, result2.totalTokens],
    ["Quality (overall)", q1?.overall, q2?.overall],
    ["Density", q1?.density, q2?.density],
    ["Diversity", q1?.diversity, q2?.diversity],
    ["Redundancy", q1?.redundancy, q2?.redundancy],
    ["Cache efficiency", result1.cacheEfficiency, result2.cacheEfficiency],
  ];

  for (const [label, v1, v2] of rows) {
    const s1 =
      v1 !== undefined
        ? typeof v1 === "number" && v1 < 10
          ? v1.toFixed(3)
          : v1.toString()
        : "n/a";
    const s2 =
      v2 !== undefined
        ? typeof v2 === "number" && v2 < 10
          ? v2.toFixed(3)
          : v2.toString()
        : "n/a";
    const delta =
      v1 !== undefined && v2 !== undefined ? (v2 - v1).toFixed(3) : "  -  ";
    const deltaColor =
      v1 !== undefined && v2 !== undefined ? (v2 >= v1 ? GREEN : RED) : DIM;
    console.log(
      `  ${WHITE}${label.padEnd(22)}${RESET} ${s1.padStart(14)} ${s2.padStart(14)} ${deltaColor}${delta.padStart(10)}${RESET}`
    );
  }

  // -- Key takeaways --

  header("Key Takeaways");

  const takeaways = [
    "Information gain filtering prevents redundant chunks from consuming budget.",
    "Budget allocation ensures each context kind (system, retrieval, conversation) gets fair share.",
    "Cache topology orders items so the stable prefix is reused across requests.",
    "Quality gate catches packs that would produce incoherent context.",
    "Under tight budgets, the pipeline drops lowest-gain items first \u2014 not randomly.",
    "The same pipeline API works whether you have 600 or 200,000 tokens.",
  ];

  for (const t of takeaways) {
    console.log(`  ${GREEN}*${RESET} ${t}`);
  }

  console.log();
}

main().catch(err => {
  console.error("Error:", err);
  process.exit(1);
});
