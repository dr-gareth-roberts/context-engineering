/**
 * Multi-Agent Entanglement — Shared Context via Pub/Sub Mesh
 *
 * Demonstrates how multiple AI agents share context discoveries through
 * an entanglement mesh. When one agent learns something, other agents
 * automatically see it in their next pack() call.
 *
 * The simulation:
 *   1. Three specialised agents: researcher, coder, reviewer
 *   2. The researcher discovers API docs and shares them
 *   3. The coder writes code and shares implementation details
 *   4. The reviewer sees both — context flows without manual wiring
 *   5. Scoped sharing, TTL expiry, and kind filtering in action
 *   6. Mesh statistics and state export/import for persistence
 *
 * No API keys needed — everything runs locally with mock data.
 * Run: npx tsx examples/multi-agent-entanglement/index.ts
 */

import type { ContextItem } from "@context-engineering/core";
import { createEntanglementMesh } from "@context-engineering/entangle";
import type {
  EntangledItem,
  AgentHandle,
  MeshStats,
} from "@context-engineering/entangle";

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
const BLUE = "\x1b[34m";

const AGENT_COLORS: Record<string, string> = {
  researcher: CYAN,
  coder: GREEN,
  reviewer: MAGENTA,
};

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
  const labelStr = String(label).padEnd(24);
  console.log(`  ${DIM}${labelStr}${RESET} ${color}${value}${RESET}`);
}

function agentTag(name: string): string {
  const color = AGENT_COLORS[name] ?? WHITE;
  return `${color}[${name}]${RESET}`;
}

function printItems(label: string, items: ContextItem[]): void {
  console.log(`  ${DIM}${label}:${RESET}`);
  if (items.length === 0) {
    console.log(`    ${DIM}(none)${RESET}`);
    return;
  }
  for (const item of items) {
    console.log(
      `    ${WHITE}${item.id.padEnd(26)}${RESET} ${DIM}kind=${item.kind}, ` +
        `${item.tokens} tokens${RESET}`
    );
  }
}

function printPending(agentName: string, pending: EntangledItem[]): void {
  const color = AGENT_COLORS[agentName] ?? WHITE;
  console.log(
    `  ${color}${agentName}${RESET} sees ${BOLD}${pending.length}${RESET} entangled items:`
  );
  for (const ei of pending) {
    const expiry = ei.expiresAt
      ? `, expires in ${Math.max(0, Math.round((ei.expiresAt - Date.now()) / 1000))}s`
      : "";
    const scope = Array.isArray(ei.scope) ? ei.scope.join(", ") : ei.scope;
    console.log(
      `    ${DIM}from ${ei.sourceAgent}:${RESET} ${ei.item.id} ` +
        `${DIM}[scope=${scope}${expiry}]${RESET}`
    );
  }
}

function printMeshStats(stats: MeshStats): void {
  metric("Total entangled items", stats.totalItems);
  metric("Active agents", stats.activeAgents);
  if (Object.keys(stats.itemsBySource).length > 0) {
    console.log(`  ${DIM}Items by source:${RESET}`);
    for (const [agent, count] of Object.entries(stats.itemsBySource)) {
      const color = AGENT_COLORS[agent] ?? WHITE;
      console.log(`    ${color}${agent.padEnd(16)}${RESET} ${count} items`);
    }
  }
  if (Object.keys(stats.itemsByScope).length > 0) {
    console.log(`  ${DIM}Items by scope:${RESET}`);
    for (const [scope, count] of Object.entries(stats.itemsByScope)) {
      console.log(`    ${DIM}${scope.padEnd(16)}${RESET} ${count} items`);
    }
  }
}

// ─── Mock Data ──────────────────────────────────────────────────────
// A feature development scenario: researcher finds docs, coder writes
// code, reviewer checks everything.

function makeItem(
  id: string,
  content: string,
  kind: string,
  tokens?: number
): ContextItem {
  return {
    id,
    content,
    kind,
    priority: 5,
    tokens: tokens ?? Math.ceil(content.split(/\s+/).length * 1.3),
  };
}

// Researcher's own context
const researcherItems: ContextItem[] = [
  makeItem(
    "task-brief",
    "Implement OAuth2 PKCE flow for the mobile app. Must support " +
      "Google, GitHub, and Apple providers. Deadline: end of sprint.",
    "task"
  ),
  makeItem(
    "research-notes",
    "OAuth2 PKCE uses code_verifier + code_challenge to prevent " +
      "authorisation code interception. No client secret needed for " +
      "public clients (mobile/SPA).",
    "notes"
  ),
];

// Items the researcher will discover and share
const discoveredDocs: ContextItem[] = [
  makeItem(
    "doc-oauth-rfc",
    "RFC 7636 — PKCE Extension: Generate code_verifier (43-128 chars, " +
      "unreserved URI chars). Derive code_challenge = BASE64URL(SHA256(code_verifier)). " +
      "Send code_challenge with authorisation request. Exchange code + code_verifier for token.",
    "docs"
  ),
  makeItem(
    "doc-google-oauth",
    "Google OAuth2 for Mobile: Use com.googleusercontent.apps.{CLIENT_ID} " +
      "as redirect URI. Enable PKCE. Request scopes: openid, email, profile. " +
      "Access token expires in 3600s — use refresh token for renewal.",
    "docs"
  ),
  makeItem(
    "doc-security-best",
    "OAuth Security Best Practices: Always use PKCE (even for confidential clients). " +
      "Validate state parameter to prevent CSRF. Use exact redirect URI matching. " +
      "Store tokens in secure storage (Keychain/Keystore), never in localStorage.",
    "docs"
  ),
];

// Coder's own context
const coderItems: ContextItem[] = [
  makeItem(
    "coder-plan",
    "Implementation plan: 1) PKCE utilities (verifier/challenge gen), " +
      "2) Provider configs (Google, GitHub, Apple), 3) Token storage abstraction, " +
      "4) Auth state machine, 5) React Native hooks.",
    "plan"
  ),
  makeItem(
    "existing-auth",
    "Current auth module uses basic username/password. AuthContext provides " +
      "login(), logout(), getToken(). Storage uses AsyncStorage (insecure for tokens).",
    "code"
  ),
];

// Items the coder will share after writing
const codeArtefacts: ContextItem[] = [
  makeItem(
    "impl-pkce-utils",
    "// pkce.ts\n" +
      "export function generateVerifier(): string {\n" +
      "  const array = crypto.getRandomValues(new Uint8Array(32));\n" +
      "  return base64url(array);\n" +
      "}\n" +
      "export async function generateChallenge(verifier: string): Promise<string> {\n" +
      "  const hash = await crypto.subtle.digest('SHA-256', encode(verifier));\n" +
      "  return base64url(new Uint8Array(hash));\n" +
      "}",
    "code"
  ),
  makeItem(
    "impl-provider-config",
    "// providers.ts\n" +
      "export const PROVIDERS = {\n" +
      "  google: { authUrl: 'https://accounts.google.com/o/oauth2/v2/auth',\n" +
      "            tokenUrl: 'https://oauth2.googleapis.com/token',\n" +
      "            scopes: ['openid', 'email', 'profile'] },\n" +
      "  github: { authUrl: 'https://github.com/login/oauth/authorize',\n" +
      "            tokenUrl: 'https://github.com/login/oauth/access_token',\n" +
      "            scopes: ['user:email'] },\n" +
      "} as const;",
    "code"
  ),
  makeItem(
    "impl-token-storage",
    "// secure-store.ts\n" +
      "import * as SecureStore from 'expo-secure-store';\n" +
      "export async function saveToken(key: string, token: string): Promise<void> {\n" +
      "  await SecureStore.setItemAsync(key, token, { keychainAccessible: WHEN_UNLOCKED });\n" +
      "}\n" +
      "export async function getToken(key: string): Promise<string | null> {\n" +
      "  return SecureStore.getItemAsync(key);\n" +
      "}",
    "code"
  ),
];

// Reviewer's own context
const reviewerItems: ContextItem[] = [
  makeItem(
    "review-checklist",
    "Code Review Checklist: 1) Security — no secrets in code, proper token storage. " +
      "2) Error handling — graceful failures, no swallowed errors. " +
      "3) Spec compliance — follows RFC exactly. " +
      "4) Test coverage — unit tests for crypto operations.",
    "checklist"
  ),
];

// ─── Main Simulation ────────────────────────────────────────────────

function main(): void {
  header("Multi-Agent Entanglement — OAuth2 Feature Development");

  console.log("  Three agents collaborate on implementing OAuth2 PKCE:");
  console.log(
    `    ${agentTag("researcher")} Finds and shares API documentation`
  );
  console.log(
    `    ${agentTag("coder")}      Writes code and shares implementation`
  );
  console.log(
    `    ${agentTag("reviewer")}   Reviews code using shared context from both\n`
  );

  // ─── Step 1: Create the Mesh ──────────────────────────────────

  subheader("Step 1: Create Entanglement Mesh");

  const mesh = createEntanglementMesh({
    defaultPropagation: "next-pack",
    maxItems: 50,
    onEntangle: (ei: EntangledItem) => {
      console.log(
        `    ${DIM}+ entangled:${RESET} ${agentTag(ei.sourceAgent)} shared ${WHITE}${ei.item.id}${RESET}`
      );
    },
  });

  // Register agents with different budgets and kind filters
  const researcher = mesh.register("researcher", {
    budget: { maxTokens: 2000 },
  });
  const coder = mesh.register("coder", {
    budget: { maxTokens: 3000 },
    kindFilter: ["docs", "code", "plan"], // only wants docs and code, not checklists
  });
  const reviewer = mesh.register("reviewer", {
    budget: { maxTokens: 4000 },
    // no kindFilter — sees everything
  });

  console.log();
  metric("Agents registered", mesh.listAgents().length);
  metric("Researcher budget", "2,000 tokens");
  metric("Coder budget", "3,000 tokens (filtered: docs, code, plan)");
  metric("Reviewer budget", "4,000 tokens (no filter — sees all)");

  // ─── Step 2: Researcher Discovers and Shares ──────────────────

  subheader("Step 2: Researcher Discovers Docs and Shares Them");
  console.log();

  // Share docs with everyone (wildcard scope)
  for (const doc of discoveredDocs) {
    researcher.entangle(doc, {
      scope: "*",
      priority: 8,
    });
  }

  console.log();

  // Check what each agent can see
  console.log(`  ${DIM}After sharing:${RESET}`);
  printPending("coder", coder.getPending());
  console.log();
  printPending("reviewer", reviewer.getPending());

  // ─── Step 3: Coder Packs with Entangled Docs ─────────────────

  subheader("Step 3: Coder Packs — Entangled Docs Auto-Injected");
  console.log();

  const coderPack = coder.pack(coderItems, { maxTokens: 3000 });

  metric("Own items", coderPack.ownItems.length);
  metric("Entangled items injected", coderPack.entangledItems.length);
  metric("Total selected", coderPack.selected.length);
  metric("Total tokens", coderPack.totalTokens);
  console.log();
  printItems("Own items", coderPack.ownItems);
  console.log();
  console.log(`  ${DIM}Entangled items (auto-injected from mesh):${RESET}`);
  for (const ei of coderPack.entangledItems) {
    console.log(
      `    ${CYAN}${ei.item.id.padEnd(26)}${RESET} ${DIM}from ${ei.sourceAgent}, ` +
        `kind=${ei.item.kind}${RESET}`
    );
  }

  // ─── Step 4: Coder Shares Implementation ──────────────────────

  subheader("Step 4: Coder Shares Implementation Code");
  console.log();

  // Share code specifically with the reviewer, with a 1-hour TTL
  for (const artefact of codeArtefacts) {
    coder.entangle(artefact, {
      scope: ["reviewer"],
      priority: 9,
      expiresIn: 3_600_000, // 1 hour
    });
  }

  console.log();
  console.log(
    `  ${DIM}Code shared with scope: [reviewer] and 1-hour TTL${RESET}`
  );

  // ─── Step 5: Reviewer Sees Everything ─────────────────────────

  subheader("Step 5: Reviewer Packs — Sees Docs + Code from Both Agents");
  console.log();

  const reviewerPending = reviewer.getPending();
  printPending("reviewer", reviewerPending);
  console.log();

  const reviewerPack = reviewer.pack(reviewerItems, { maxTokens: 4000 });

  metric("Own items", reviewerPack.ownItems.length);
  metric("Entangled items injected", reviewerPack.entangledItems.length);
  metric("Total selected", reviewerPack.selected.length);
  metric("Total tokens", reviewerPack.totalTokens);

  console.log();
  console.log(`  ${DIM}Sources in reviewer's context:${RESET}`);
  const sourceMap = new Map<string, number>();
  for (const item of reviewerPack.selected) {
    const entangled = reviewerPack.entangledItems.find(
      ei => ei.item.id === item.id
    );
    const source = entangled ? entangled.sourceAgent : "reviewer (own)";
    sourceMap.set(source, (sourceMap.get(source) ?? 0) + 1);
  }
  for (const [source, count] of sourceMap) {
    const color = AGENT_COLORS[source] ?? WHITE;
    console.log(`    ${color}${source.padEnd(20)}${RESET} ${count} items`);
  }

  // ─── Step 6: Scoped Sharing Demo ──────────────────────────────

  subheader("Step 6: Scoped Sharing — Only Targeted Agents See Items");
  console.log();

  // Researcher shares a security note only with the reviewer
  researcher.entangle(
    makeItem(
      "security-note",
      "IMPORTANT: The existing AsyncStorage token storage is insecure. " +
        "Must migrate to SecureStore before merging the OAuth PR.",
      "security"
    ),
    {
      scope: ["reviewer"],
      priority: 10,
    }
  );

  console.log();

  // Verify scoping
  const coderPendingAfter = coder.getPending();
  const reviewerPendingAfter = reviewer.getPending();

  const coderSeesNote = coderPendingAfter.some(
    ei => ei.item.id === "security-note"
  );
  const reviewerSeesNote = reviewerPendingAfter.some(
    ei => ei.item.id === "security-note"
  );

  console.log(
    `  ${agentTag("coder")} sees security-note? ` +
      `${coderSeesNote ? `${RED}YES (unexpected)` : `${GREEN}NO (correct — not in scope)`}${RESET}`
  );
  console.log(
    `  ${agentTag("reviewer")} sees security-note? ` +
      `${reviewerSeesNote ? `${GREEN}YES (correct — in scope)` : `${RED}NO (unexpected)`}${RESET}`
  );

  // ─── Step 7: Mesh Statistics ──────────────────────────────────

  subheader("Step 7: Mesh Statistics");
  console.log();

  printMeshStats(mesh.stats());

  // ─── Step 8: State Export/Import ──────────────────────────────

  subheader("Step 8: Export and Restore Mesh State");
  console.log();

  const exported = mesh.exportState();
  metric("Exported items", exported.items.length);
  metric("Exported agents", exported.agents.length);

  // Create a fresh mesh and import
  const mesh2 = createEntanglementMesh({ defaultPropagation: "next-pack" });
  mesh2.importState(exported);

  const restoredStats = mesh2.stats();
  console.log();
  console.log(`  ${GREEN}Restored mesh:${RESET}`);
  metric("Total items", restoredStats.totalItems);
  metric("Active agents", restoredStats.activeAgents);

  // Verify a restored agent can still see entangled items
  const restoredReviewer = mesh2.getAgent("reviewer");
  if (restoredReviewer) {
    const restoredPending = restoredReviewer.getPending();
    console.log();
    console.log(
      `  ${DIM}Restored reviewer still sees ${restoredPending.length} pending items${RESET}`
    );
  }

  // ─── Summary ──────────────────────────────────────────────────

  header("Summary");

  console.log("  The Entanglement Mesh provides:");
  console.log(
    `    ${GREEN}1.${RESET} Automatic context sharing — no manual passing between agents`
  );
  console.log(
    `    ${GREEN}2.${RESET} Scoped propagation — control which agents see what`
  );
  console.log(
    `    ${GREEN}3.${RESET} Kind filtering — agents only receive item types they need`
  );
  console.log(
    `    ${GREEN}4.${RESET} TTL expiry — shared items auto-expire after a duration`
  );
  console.log(
    `    ${GREEN}5.${RESET} Budget-aware injection — entangled items respect token limits`
  );
  console.log(
    `    ${GREEN}6.${RESET} State export/import — persist mesh across restarts`
  );
  console.log();
  console.log(
    `  ${DIM}See docs/wiki/Multi-Agent-Entanglement.md for the full guide.${RESET}\n`
  );
}

main();
