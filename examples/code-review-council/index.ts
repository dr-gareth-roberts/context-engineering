/**
 * Multi-Model Code Review Council
 *
 * Demonstrates the Council of Experts package by assembling three reviewers
 * with distinct perspectives — Architect, Security Lead, Performance Engineer —
 * and running them through a structured debate on a realistic code change.
 *
 * Because this example uses mock providers (no API keys needed), the responses
 * are pre-written but realistic. The value is seeing the council orchestration:
 * round management, cross-expert visibility, synthesis, and convergence scoring.
 *
 * Run: npx tsx examples/code-review-council/index.ts
 */

import {
  createCouncil,
  ROLE_PRESETS,
  type CouncilLLMProvider,
  type CouncilMessage,
} from "@context-engineering/council";

// ---------------------------------------------------------------------------
// 1. The code change under review
// ---------------------------------------------------------------------------

const CODE_DIFF = `
diff --git a/src/routes/users.ts b/src/routes/users.ts
index 3a1f2c8..9d4e7b1 100644
--- a/src/routes/users.ts
+++ b/src/routes/users.ts
@@ -1,5 +1,8 @@
 import { Router } from 'express';
+import { authenticateToken } from '../middleware/auth';
 import { db } from '../db';
+import { z } from 'zod';
+import { rateLimit } from 'express-rate-limit';

 const router = Router();

+const limiter = rateLimit({ windowMs: 15 * 60 * 1000, max: 100 });
+
+const UserSearchSchema = z.object({
+  query: z.string().min(1).max(200),
+  role: z.enum(['admin', 'member', 'viewer']).optional(),
+  page: z.coerce.number().int().min(1).default(1),
+  limit: z.coerce.number().int().min(1).max(100).default(20),
+});
+
+// GET /api/users/search — search users by name/email with role filter
+router.get('/search', authenticateToken, limiter, async (req, res) => {
+  try {
+    const params = UserSearchSchema.parse(req.query);
+    const offset = (params.page - 1) * params.limit;
+
+    const users = await db.query(
+      \`SELECT id, name, email, role, created_at
+       FROM users
+       WHERE (name ILIKE $1 OR email ILIKE $1)
+         AND ($2::text IS NULL OR role = $2)
+       ORDER BY created_at DESC
+       LIMIT $3 OFFSET $4\`,
+      [\`%\${params.query}%\`, params.role ?? null, params.limit, offset]
+    );
+
+    const countResult = await db.query(
+      \`SELECT COUNT(*) as total FROM users
+       WHERE (name ILIKE $1 OR email ILIKE $1)
+         AND ($2::text IS NULL OR role = $2)\`,
+      [\`%\${params.query}%\`, params.role ?? null]
+    );
+
+    res.json({
+      users: users.rows,
+      pagination: {
+        page: params.page,
+        limit: params.limit,
+        total: parseInt(countResult.rows[0].total, 10),
+      },
+    });
+  } catch (err) {
+    if (err instanceof z.ZodError) {
+      return res.status(400).json({ errors: err.flatten().fieldErrors });
+    }
+    console.error('User search failed:', err);
+    res.status(500).json({ error: 'Internal server error' });
+  }
+});
`;

const REVIEW_QUERY = `Review this pull request that adds a user search endpoint with authentication, input validation, pagination, and rate limiting. Identify issues, suggest improvements, and note what was done well.

${CODE_DIFF}`;

// ---------------------------------------------------------------------------
// 2. Mock responses — realistic, role-specific, and round-aware
// ---------------------------------------------------------------------------

const ARCHITECT_ROUND_1 = `## Architectural Review

**What's done well:**
The endpoint follows a clean request-validate-query-respond pattern, which is the right structural choice. Using Zod for schema validation at the boundary is solid — it keeps the validation declarative and co-located with the route. Separating auth middleware from the route handler is correct layering.

**Concerns:**

1. **Missing service layer.** The route handler directly queries the database. This couples your HTTP layer to your persistence layer, making it harder to test, reuse, or swap storage. Extract a \`UserService.search()\` method that the route delegates to.

2. **Two sequential queries for data + count.** This is a common pattern but it means every search hits the database twice. Consider using a CTE or \`COUNT(*) OVER()\` window function to get both in one round-trip. At scale, this matters.

3. **No response DTO.** The raw database rows (including \`created_at\` internals) are returned directly. Define a response shape explicitly — this protects you from leaking columns added later.

4. **Error handling is too broad.** The catch block distinguishes Zod errors from everything else, but a database connection timeout and a query syntax error both become 500s. Consider distinguishing operational errors from programmer errors.

5. **Rate limiter is route-scoped but config is module-scoped.** If this router is mounted in multiple places, the limiter state could behave unexpectedly. Consider centralizing rate limit configuration.

**Recommendation:** Approve with required changes — extract the service layer and add a response DTO before merging.`;

const ARCHITECT_ROUND_2 = `## Architectural Review — Revised Position

After considering the Security Lead's and Performance Engineer's feedback, I want to refine my recommendations:

**Points of agreement:**
- The Security Lead's concern about returning \`email\` to non-admin callers is valid and reinforces my point about needing a response DTO. The DTO should be role-aware — admins see email, regular users see name + role only.
- The Performance Engineer's point about the ILIKE pattern preventing index usage is important. This shifts my recommendation: rather than just extracting a service layer, the service should encapsulate a proper full-text search strategy (pg_trgm or a search index).

**Revised concerns:**
1. **Service layer** — still required, but now with an additional reason: the service can enforce field-level access control based on the caller's role, which addresses both architectural and security concerns in one place.
2. **The two-query pattern** — I maintain this should be a single query with window functions. The Performance Engineer's caching suggestion is a good optimization on top, but the base query should be efficient first.
3. **Adding a repository pattern** may be premature at this stage. A simple service function is sufficient until there are multiple storage backends.

**Where I disagree:**
- I don't think we need Redis caching for this endpoint yet (Performance Engineer's suggestion). Optimizing the query and adding appropriate database indexes should be the first step. Cache when you have evidence of a bottleneck, not preemptively.

**Final recommendation:** Approve with required changes — service layer with role-based response shaping, single-query pagination, and a full-text search strategy.`;

const SECURITY_ROUND_1 = `## Security Review

**Positive observations:**
Authentication via \`authenticateToken\` middleware is present, which is the baseline requirement. Rate limiting is applied, which mitigates brute-force enumeration. Input validation with Zod prevents most injection vectors through type coercion.

**Critical issues:**

1. **User enumeration risk.** The search endpoint returns user emails to any authenticated user. An attacker with a valid token (even a low-privilege "viewer" account) can enumerate all users in the system, harvest email addresses, and use them for phishing or credential stuffing. **Mitigation:** Restrict email visibility to admin/manager roles, or return only masked emails (e.g., \`g***@example.com\`).

2. **No authorization check.** Authentication is not authorization. The endpoint verifies the caller has a valid token but doesn't check whether they're allowed to search users. A viewer-role user probably shouldn't be able to search by role=admin. **Mitigation:** Add role-based access control — at minimum, restrict the \`role\` filter parameter to admin users.

3. **SQL injection via ILIKE pattern.** While Zod validates the query string length, it doesn't sanitize ILIKE metacharacters (\`%\`, \`_\`). A query like \`%\` returns all users. A query like \`____\` matches all 4-character names. **Mitigation:** Escape ILIKE special characters in the query parameter before interpolation.

4. **Missing audit trail.** User search is a sensitive operation — who searched for whom should be logged for compliance (SOC 2, GDPR data access logging). **Mitigation:** Add structured audit logging with caller identity and search parameters.

5. **Rate limit is per-IP, not per-user.** Behind a load balancer or shared NAT, multiple users share an IP. A determined attacker can also rotate IPs. **Mitigation:** Use token-based rate limiting (req.user.id) in addition to IP-based.

**Verdict:** Request changes. Issues 1 and 2 are blockers — the endpoint leaks PII and lacks authorization.`;

const SECURITY_ROUND_2 = `## Security Review — Revised Position

The Architect's and Performance Engineer's responses have clarified some trade-offs. Here's my updated assessment:

**Strong agreement:**
- The Architect's proposal for a service layer with role-based response shaping directly solves my top concern (PII exposure). If the service layer controls which fields are returned based on the caller's role, issues 1 and 2 are addressed architecturally rather than with ad-hoc checks. I strongly support this approach.
- The Architect's response DTO idea is the right vehicle for field-level access control.

**Maintained positions:**
- **ILIKE metacharacter escaping** remains a concern regardless of architectural changes. Even with a full-text search approach (as the Performance Engineer suggests), input sanitization at the boundary is non-negotiable. Whether you use ILIKE or tsvector, the search input must be sanitized.
- **Audit logging** is still required. This is a compliance obligation, not an optimization. It should be added before merge, not deferred.

**New concern raised by discussion:**
- If we add caching (as the Performance Engineer suggests), cached results must respect the caller's authorization level. A cached response generated for an admin (containing emails) must never be served to a viewer. Cache keys must include the caller's role. This is a common and dangerous cache poisoning vector.

**Adjusted positions:**
- I agree the rate limiter concern (per-IP vs per-user) can be a fast-follow rather than a blocker, provided the other issues are addressed.

**Final verdict:** Request changes. The service-layer-with-role-based-DTO approach resolves my top two blockers, but ILIKE sanitization and audit logging must also be addressed before merge. Three required changes total.`;

const PERFORMANCE_ROUND_1 = `## Performance Review

**Positive aspects:**
Pagination is implemented correctly with LIMIT/OFFSET, which prevents unbounded result sets. The rate limiter provides basic protection against query floods. Zod's \`max(100)\` on the limit parameter caps the per-request cost.

**Performance concerns:**

1. **ILIKE with leading wildcard kills indexes.** The pattern \`%query%\` forces a sequential scan on every request. On a users table with 100K+ rows, this means ~50-200ms per query instead of <5ms. **Fix:** Use PostgreSQL's \`pg_trgm\` extension with a GIN index, or maintain a separate \`tsvector\` column with a GiST index for full-text search. Either approach drops search time to <10ms regardless of table size.

2. **Two separate queries (N+1 at the endpoint level).** The data query and count query execute sequentially, doubling the round-trip latency. At p50 this adds ~5-15ms, but at p99 with connection pool contention it can add 100ms+. **Fix:** Use \`SELECT *, COUNT(*) OVER() as total_count FROM users WHERE ... LIMIT $3 OFFSET $4\` to combine them into a single query.

3. **OFFSET-based pagination degrades linearly.** Page 1 is fast, page 500 is slow — the database must skip all preceding rows. With 100K users and a limit of 20, page 5000 scans 100K rows to return 20. **Fix:** Use cursor-based pagination (keyset pagination) with \`WHERE created_at < $last_seen_timestamp ORDER BY created_at DESC LIMIT $limit\`. This is O(1) regardless of page depth.

4. **No caching layer.** User search results are relatively stable (users don't change names frequently). A 30-60 second Redis cache with a cache key of \`search:{query}:{role}:{page}\` would eliminate redundant database hits for repeated searches.

5. **Missing database connection handling.** The \`db.query()\` calls don't specify a timeout. A slow query can hold a connection pool slot indefinitely. **Fix:** Add a statement timeout: \`SET statement_timeout = '5s'\` or use the client's query timeout option.

**Benchmark estimate:** Current implementation at 100K users: ~200ms p50, ~800ms p99. With fixes: ~8ms p50, ~25ms p99.

**Verdict:** Approve with requested changes. The ILIKE index issue is a blocking performance concern; the others are strong recommendations.`;

const PERFORMANCE_ROUND_2 = `## Performance Review — Revised Position

The other reviewers have raised points that affect my performance recommendations. Updated analysis:

**Agreement with Architect:**
- Extracting a service layer is a good idea from a performance perspective too — it provides a natural place to add caching, query optimization, and instrumentation without cluttering the route handler. The service can own the decision of whether to use ILIKE, pg_trgm, or an external search index.
- Single-query pagination with window functions: fully agree. My original recommendation stands, and the Architect's endorsement strengthens the case.

**Agreement with Security Lead:**
- The cache poisoning concern is critical and well-spotted. If we add caching (my recommendation #4), the cache key MUST include the caller's role to prevent cross-role data leakage. Updated recommendation: cache key should be \`search:{callerRole}:{query}:{role}:{page}\`.
- I hadn't considered that ILIKE metacharacter abuse is also a performance issue — a query of just \`%\` matches every row and bypasses the intent of pagination. Input sanitization serves both security and performance.

**Refined recommendations:**
1. **Primary:** Add pg_trgm GIN index — this is the single highest-impact change. Transforms worst-case from 200ms to <10ms.
2. **Secondary:** Combine data + count into a single window function query.
3. **Tertiary:** Switch to cursor-based pagination (can be a follow-up PR if the team prefers incremental changes).
4. **Deferred:** Redis caching layer — I'm persuaded by the Architect's point that we should optimize the query first and add caching only when we have evidence of a bottleneck. However, the schema should be designed cache-ready (deterministic query normalization, role in the key).

**Revised benchmark estimate:** With pg_trgm index + single query: ~5ms p50, ~15ms p99 at 100K users. Good enough to ship without a cache layer.

**Verdict:** Approve with required change: pg_trgm index. Strongly recommend single-query pagination. Cursor pagination and caching as follow-ups.`;

// The synthesizer combines all perspectives into a final, unified review
const SYNTHESIS_RESPONSE = `## Code Review Council — Synthesized Review

### Verdict: Request Changes (3 required, 4 recommended)

### Summary
This PR adds a well-structured user search endpoint with authentication, validation, rate limiting, and pagination. The foundational choices are sound. However, the council identified security gaps, a performance bottleneck, and an architectural improvement that should be addressed before merging.

### Required Changes

1. **Extract a service layer with role-based response shaping**
   *Consensus across all three reviewers.* Move the database query logic into a \`UserService.search()\` method. The service should control which fields are returned based on the caller's role — admins see full records including email; viewers see name and role only. This addresses the PII exposure risk (Security), improves testability (Architect), and provides a natural place for query optimization (Performance).

2. **Add a pg_trgm GIN index for search**
   *Architect + Performance agree; Security neutral.* The current \`ILIKE '%query%'\` pattern forces sequential scans. Adding \`CREATE EXTENSION pg_trgm; CREATE INDEX idx_users_search ON users USING GIN (name gin_trgm_ops, email gin_trgm_ops);\` drops query time from ~200ms to <10ms at scale.

3. **Sanitize ILIKE metacharacters and add audit logging**
   *Security requirement; Performance agrees on sanitization.* Escape \`%\` and \`_\` in user input before building the ILIKE pattern. Add structured audit logging for compliance (caller identity, search parameters, timestamp).

### Recommended Improvements

4. **Combine data + count into a single query** using \`COUNT(*) OVER()\` window function. Eliminates a redundant database round-trip. (Architect + Performance)

5. **Plan migration to cursor-based pagination** for deep page performance. Can be a follow-up PR. (Performance)

6. **Add query/connection timeouts** to prevent slow queries from exhausting the connection pool. (Performance)

7. **Design cache keys to include caller role** if caching is added later, to prevent cross-role data leakage. (Security + Performance)

### What Was Done Well
- Authentication middleware is correctly applied
- Zod schema validation is declarative and thorough
- Rate limiting is present from the start
- Pagination prevents unbounded result sets
- Error handling distinguishes validation errors from server errors

### Disagreements Resolved
- **Caching:** The Architect and Performance Engineer debated whether to add Redis caching now. The council recommends deferring caching until query optimization (pg_trgm + single query) is measured in production. Design for cache-readiness but don't add the infrastructure yet.
- **Repository pattern:** The Architect initially suggested this but revised to a simpler service function, which the council agrees is appropriate at this scale.`;

// ---------------------------------------------------------------------------
// 3. Mock providers that return pre-written, role-specific reviews
// ---------------------------------------------------------------------------

/**
 * Creates a mock LLM provider that returns different responses based on
 * which round the council is in. The provider tracks call count to
 * determine the current round.
 */
function createMockProvider(
  modelName: string,
  round1Response: string,
  round2Response: string
): CouncilLLMProvider {
  let callCount = 0;

  return {
    async generate(_messages: CouncilMessage[], options?: { model?: string }) {
      callCount++;
      // Odd calls are round 1, even calls are round 2
      // (the council calls each provider once per round)
      const isFirstRound = callCount <= 1;
      const text = isFirstRound ? round1Response : round2Response;
      const tokenEstimate = Math.ceil(text.split(/\s+/).length * 1.3);

      return {
        text,
        model: options?.model ?? modelName,
        usage: { totalTokens: tokenEstimate },
      };
    },
  };
}

/** Mock synthesizer that returns the pre-written combined review. */
function createSynthesizerProvider(): CouncilLLMProvider {
  return {
    async generate(_messages: CouncilMessage[], options?: { model?: string }) {
      const tokenEstimate = Math.ceil(
        SYNTHESIS_RESPONSE.split(/\s+/).length * 1.3
      );
      return {
        text: SYNTHESIS_RESPONSE,
        model: options?.model ?? "mock-synthesizer",
        usage: { totalTokens: tokenEstimate },
      };
    },
  };
}

// ---------------------------------------------------------------------------
// 4. Output formatting helpers
// ---------------------------------------------------------------------------

function banner(text: string): void {
  const line = "=".repeat(72);
  console.log(`\n${line}`);
  console.log(`  ${text}`);
  console.log(line);
}

function sectionHeader(text: string): void {
  console.log(`\n${"─".repeat(72)}`);
  console.log(`  ${text}`);
  console.log("─".repeat(72));
}

function formatDuration(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`;
}

// ---------------------------------------------------------------------------
// 5. Main: run the council
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  banner("CODE REVIEW COUNCIL — Multi-Model Deliberation Demo");

  console.log("\nScenario: Three experts review a PR that adds a user search");
  console.log("endpoint with authentication, validation, and pagination.\n");
  console.log("Experts:");
  console.log(
    "  1. Architect        (pragmatist)    — design & maintainability"
  );
  console.log(
    "  2. Security Lead    (critic)        — auth, injection, data exposure"
  );
  console.log(
    "  3. Perf. Engineer   (domain-expert) — latency, caching, queries"
  );

  // -- DEBATE STRATEGY -------------------------------------------------------

  banner("STRATEGY 1: Debate (2 rounds, attributed)");
  console.log("\nIn debate mode, each expert sees the others' responses after");
  console.log("round 1 and refines their position in round 2.\n");

  // Create the three council members using ROLE_PRESETS for system prompts.
  // Each gets a mock provider loaded with role-appropriate responses.
  const debateCouncil = createCouncil({
    members: [
      {
        id: "architect",
        name: "Architect",
        ...ROLE_PRESETS["pragmatist"],
        provider: createMockProvider(
          "claude-opus-4-6",
          ARCHITECT_ROUND_1,
          ARCHITECT_ROUND_2
        ),
        model: "claude-opus-4-6",
        temperature: 0.7,
        maxTokens: 2048,
      },
      {
        id: "security",
        name: "Security Lead",
        ...ROLE_PRESETS["critic"],
        provider: createMockProvider(
          "gpt-4.1",
          SECURITY_ROUND_1,
          SECURITY_ROUND_2
        ),
        model: "gpt-4.1",
        temperature: 0.5,
        maxTokens: 2048,
      },
      {
        id: "performance",
        name: "Performance Engineer",
        ...ROLE_PRESETS["domain-expert"],
        provider: createMockProvider(
          "claude-sonnet-4-20250514",
          PERFORMANCE_ROUND_1,
          PERFORMANCE_ROUND_2
        ),
        model: "claude-sonnet-4-20250514",
        temperature: 0.6,
        maxTokens: 2048,
      },
    ],
    strategy: "debate",
    rounds: 2,
    synthesizer: {
      provider: createSynthesizerProvider(),
      model: "claude-opus-4-6",
      maxTokens: 4096,
    },
    // Live callbacks show progress as the council deliberates
    onMemberResponse: event => {
      console.log(
        `  [Round ${event.round}] ${event.memberName} responded (${event.tokenCount} tokens)`
      );
    },
    onRoundComplete: event => {
      console.log(
        `\n  >> Round ${event.round}/${event.totalRounds} complete ` +
          `(${event.responses.length} responses)\n`
      );
    },
  });

  console.log("Running deliberation...\n");

  const debateResult = await debateCouncil.deliberate({
    query: REVIEW_QUERY,
    rounds: 2,
  });

  // Display each round's responses
  for (const round of debateResult.rounds) {
    sectionHeader(`Round ${round.round} of ${debateResult.roundCount}`);
    for (const response of round.responses) {
      console.log(`\n[${response.memberName}] (${response.model}):`);
      console.log(response.response);
    }
  }

  // Display the synthesized final review
  sectionHeader("SYNTHESIZED REVIEW");
  console.log(`\n${debateResult.synthesis}`);

  // Display token usage per expert
  sectionHeader("TOKEN USAGE");
  for (const [memberId, tokens] of Object.entries(
    debateResult.tokensByMember
  )) {
    const label = memberId === "_synthesizer" ? "Synthesizer" : memberId;
    console.log(`  ${label.padEnd(20)} ${tokens.toLocaleString()} tokens`);
  }
  console.log(
    `  ${"TOTAL".padEnd(20)} ${debateResult.totalTokens.toLocaleString()} tokens`
  );
  console.log(
    `  ${"Duration".padEnd(20)} ${formatDuration(debateResult.durationMs)}`
  );
  console.log(`  ${"Strategy".padEnd(20)} ${debateResult.strategy}`);
  console.log(`  ${"Rounds".padEnd(20)} ${debateResult.roundCount}`);

  // -- DELPHI STRATEGY --------------------------------------------------------

  banner("STRATEGY 2: Delphi (anonymous, with convergence scoring)");
  console.log(
    "\nIn Delphi mode, expert identities are hidden from each other."
  );
  console.log("The council tracks convergence — how much the experts agree —");
  console.log("and can stop early if consensus is reached.\n");

  // Reuse the same expert profiles but with fresh mock providers
  const delphiCouncil = createCouncil({
    members: [
      {
        id: "architect",
        name: "Architect",
        ...ROLE_PRESETS["pragmatist"],
        provider: createMockProvider(
          "claude-opus-4-6",
          ARCHITECT_ROUND_1,
          ARCHITECT_ROUND_2
        ),
        model: "claude-opus-4-6",
        temperature: 0.7,
        maxTokens: 2048,
      },
      {
        id: "security",
        name: "Security Lead",
        ...ROLE_PRESETS["critic"],
        provider: createMockProvider(
          "gpt-4.1",
          SECURITY_ROUND_1,
          SECURITY_ROUND_2
        ),
        model: "gpt-4.1",
        temperature: 0.5,
        maxTokens: 2048,
      },
      {
        id: "performance",
        name: "Performance Engineer",
        ...ROLE_PRESETS["domain-expert"],
        provider: createMockProvider(
          "claude-sonnet-4-20250514",
          PERFORMANCE_ROUND_1,
          PERFORMANCE_ROUND_2
        ),
        model: "claude-sonnet-4-20250514",
        temperature: 0.6,
        maxTokens: 2048,
      },
    ],
    strategy: "delphi",
    rounds: 3,
    convergenceThreshold: 0.85,
    synthesizer: {
      provider: createSynthesizerProvider(),
      model: "claude-opus-4-6",
      maxTokens: 4096,
    },
    onRoundComplete: event => {
      const score =
        event.convergenceScore !== undefined
          ? ` | convergence: ${(event.convergenceScore * 100).toFixed(1)}%`
          : "";
      console.log(
        `  >> Round ${event.round}/${event.totalRounds} complete${score}`
      );
    },
  });

  console.log("Running Delphi deliberation...\n");

  const delphiResult = await delphiCouncil.deliberate({
    query: REVIEW_QUERY,
    rounds: 3,
  });

  // Display convergence progression
  sectionHeader("CONVERGENCE PROGRESSION");
  for (const round of delphiResult.rounds) {
    const score =
      round.convergenceScore !== undefined
        ? `${(round.convergenceScore * 100).toFixed(1)}%`
        : "N/A";
    const bar =
      round.convergenceScore !== undefined
        ? "#".repeat(Math.round(round.convergenceScore * 40)).padEnd(40, ".")
        : ".".repeat(40);
    console.log(`  Round ${round.round}: [${bar}] ${score}`);
  }

  if (delphiResult.convergedEarly) {
    console.log(
      `\n  Council converged early at round ${delphiResult.roundCount}!`
    );
  } else {
    console.log(`\n  Council completed all ${delphiResult.roundCount} rounds.`);
  }

  sectionHeader("DELPHI SUMMARY");
  console.log(`  Strategy:            ${delphiResult.strategy}`);
  console.log(`  Rounds executed:     ${delphiResult.roundCount}`);
  console.log(
    `  Final convergence:   ${delphiResult.convergenceScore !== undefined ? (delphiResult.convergenceScore * 100).toFixed(1) + "%" : "N/A"}`
  );
  console.log(
    `  Converged early:     ${delphiResult.convergedEarly ? "yes" : "no"}`
  );
  console.log(
    `  Total tokens:        ${delphiResult.totalTokens.toLocaleString()}`
  );
  console.log(
    `  Duration:            ${formatDuration(delphiResult.durationMs)}`
  );

  banner("DEMO COMPLETE");
  console.log("\nThis example demonstrated two council strategies:");
  console.log("  - Debate: experts see each other and refine positions");
  console.log("  - Delphi: anonymous deliberation with convergence tracking\n");
  console.log("With real LLM providers, replace the mock providers with");
  console.log("actual API clients from @context-engineering/providers.\n");
}

main().catch(err => {
  console.error("Council deliberation failed:", err);
  process.exit(1);
});
