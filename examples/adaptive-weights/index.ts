/**
 * Adaptive Weight Learning — Learn Optimal Scoring Weights from Feedback
 *
 * Demonstrates how the adaptive optimizer learns which scoring dimensions
 * (priority, recency, salience, relevance) matter most for your use case
 * by analysing the correlation between item features and outcome quality.
 *
 * The simulation:
 *   1. Creates an optimizer with equal base weights
 *   2. Runs 30 pack-and-feedback cycles simulating a customer support bot
 *   3. Reports which quality signal produces high-quality responses (recency)
 *   4. Shows how learned weights shift toward the most impactful dimension
 *   5. Compares pack results before and after adaptation
 *   6. Exports and imports optimizer state for persistence
 *
 * No API keys needed — quality scores are simulated based on item freshness.
 * Run: npx tsx examples/adaptive-weights/index.ts
 */

import type { ContextItem } from "@context-engineering/core";
import { pack } from "@context-engineering/core";
import {
  createContextOptimizer,
  InMemoryFeedbackStore,
} from "@context-engineering/adaptive";
import type {
  WeightInsights,
  OptimizedPack,
} from "@context-engineering/adaptive";

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
  const labelStr = String(label).padEnd(24);
  console.log(`  ${DIM}${labelStr}${RESET} ${color}${value}${RESET}`);
}

function bar(ratio: number, width = 25): string {
  const clamped = Math.max(0, Math.min(1, ratio));
  const filled = Math.round(clamped * width);
  const empty = width - filled;
  const colour = clamped > 0.7 ? GREEN : clamped > 0.4 ? YELLOW : RED;
  return `${colour}${"█".repeat(filled)}${DIM}${"░".repeat(empty)}${RESET}`;
}

function fmtWeight(w: number): string {
  const color = w > 1.5 ? GREEN : w < 0.5 ? RED : WHITE;
  return `${color}${w.toFixed(3)}${RESET}`;
}

// ─── Mock Data: Customer Support Knowledge Base ─────────────────────
// Simulates a support bot with tickets, docs, and conversation history.
// The key insight: for support bots, recency matters most because
// customers ask about their latest issue, not old resolved tickets.

function generateSupportItems(turn: number): ContextItem[] {
  const items: ContextItem[] = [];

  // System prompt — always included
  items.push({
    id: "system",
    content:
      "You are a customer support agent for a SaaS platform. " +
      "Be empathetic, precise, and reference the customer's specific issue. " +
      "Always check recent tickets before suggesting generic solutions.",
    kind: "system",
    priority: 10,
    recency: 10,
    salience: 5,
    tokens: 45,
  });

  // Knowledge base articles (high priority but varying freshness)
  const articles = [
    {
      id: "kb-billing",
      content:
        "Billing FAQ: Invoices are generated on the 1st. Refunds take 5-7 days. " +
        "Enterprise plans support purchase orders. Contact billing@example.com for disputes.",
      priority: 8,
      recency: 2,
      salience: 3,
    },
    {
      id: "kb-api-errors",
      content:
        "Common API Errors: 401 means expired token — regenerate in Settings > API. " +
        "429 means rate limit — implement exponential backoff. 503 means maintenance window.",
      priority: 7,
      recency: 3,
      salience: 4,
    },
    {
      id: "kb-onboarding",
      content:
        "Onboarding Guide: Create workspace, invite team, configure SSO, set up webhooks. " +
        "The setup wizard handles most configuration automatically.",
      priority: 5,
      recency: 1,
      salience: 2,
    },
    {
      id: "kb-outage-jan",
      content:
        "January Outage Post-mortem: Database failover triggered by disk pressure. " +
        "Root cause was uncompacted SST files. Mitigation: automated compaction schedule.",
      priority: 4,
      recency: 1,
      salience: 1,
    },
  ];

  for (const a of articles) {
    items.push({
      id: a.id,
      content: a.content,
      kind: "docs",
      priority: a.priority,
      recency: a.recency,
      salience: a.salience,
      tokens: Math.ceil(a.content.split(/\s+/).length * 1.3),
    });
  }

  // Recent customer tickets (high recency, varying priority)
  const recentTickets = [
    {
      id: `ticket-${turn}-api`,
      content:
        `Customer reports 401 errors since upgrading to v3.2. Their API key was ` +
        `regenerated yesterday but still fails. Environment: production, region: eu-west-1.`,
      priority: 6,
      recency: 9,
      salience: 8,
    },
    {
      id: `ticket-${turn}-billing`,
      content:
        `Customer charged twice for March. Payment IDs: pay_abc123 and pay_def456. ` +
        `They are on the Pro plan ($49/month). Need immediate refund for duplicate.`,
      priority: 7,
      recency: 10,
      salience: 9,
    },
    {
      id: `ticket-${turn}-slow`,
      content:
        `Dashboard loading times increased from 200ms to 3s since last deploy. ` +
        `Affects all users in the customer's workspace. No errors in browser console.`,
      priority: 5,
      recency: 8,
      salience: 7,
    },
  ];

  for (const t of recentTickets) {
    items.push({
      id: t.id,
      content: t.content,
      kind: "ticket",
      priority: t.priority,
      recency: t.recency,
      salience: t.salience,
      tokens: Math.ceil(t.content.split(/\s+/).length * 1.3),
    });
  }

  // Old resolved tickets (low recency — should be deprioritised)
  items.push({
    id: `resolved-${turn}-old`,
    content:
      "Resolved: Customer couldn't log in — was using wrong subdomain. " +
      "Redirected to correct workspace URL. Closed.",
    kind: "ticket",
    priority: 2,
    recency: 1,
    salience: 1,
    tokens: 30,
  });

  // Current conversation
  items.push({
    id: `conv-${turn}`,
    content:
      `Turn ${turn}: Customer asks about the duplicate billing charge and wants ` +
      `to know when the refund will appear on their statement.`,
    kind: "conversation",
    priority: 8,
    recency: 10,
    salience: 10,
    tokens: 30,
  });

  return items;
}

/**
 * Simulates response quality based on which items were selected.
 * In reality, you'd evaluate the actual model response — here we
 * reward packs that include recent, relevant tickets over stale docs.
 */
function simulateQuality(selected: ContextItem[], turn: number): number {
  let score = 0.4; // baseline

  const hasCurrentConversation = selected.some(i => i.id === `conv-${turn}`);
  const hasRecentTicket = selected.some(
    i => i.kind === "ticket" && (i.recency ?? 0) >= 8
  );
  const hasStaleOnly = selected
    .filter(i => i.kind === "ticket")
    .every(i => (i.recency ?? 0) < 5);
  const hasSystem = selected.some(i => i.kind === "system");

  if (hasSystem) score += 0.1;
  if (hasCurrentConversation) score += 0.15;
  if (hasRecentTicket) score += 0.25;
  if (hasStaleOnly) score -= 0.2;

  // Add slight noise for realism
  score += Math.sin(turn * 7.3) * 0.05;

  return Math.max(0, Math.min(1, score));
}

// ─── Main Simulation ────────────────────────────────────────────────

async function main(): Promise<void> {
  header("Adaptive Weight Learning — Customer Support Bot");

  console.log(
    "  This simulation trains an optimizer to learn that for a support bot,"
  );
  console.log(
    "  recency matters most — customers care about their latest issue,"
  );
  console.log("  not old resolved tickets or stale knowledge base articles.\n");

  // ─── Phase 1: Setup ─────────────────────────────────────────────

  subheader("Phase 1: Initialise with Equal Weights");

  const store = new InMemoryFeedbackStore();
  const optimizer = createContextOptimizer({
    feedback: "explicit",
    learningRate: 0.15,
    regularization: 0.05,
    minSamples: 5,
    baseWeights: { priority: 1.0, recency: 1.0, salience: 1.0, relevance: 1.0 },
    store,
  });

  const initialInsights = await optimizer.getInsights();
  console.log();
  metric("Priority weight", fmtWeight(initialInsights.currentWeights.priority));
  metric("Recency weight", fmtWeight(initialInsights.currentWeights.recency));
  metric("Salience weight", fmtWeight(initialInsights.currentWeights.salience));
  metric(
    "Relevance weight",
    fmtWeight(initialInsights.currentWeights.relevance ?? 1)
  );
  metric("Confidence", `${(initialInsights.confidence * 100).toFixed(1)}%`);

  // ─── Phase 2: Training Loop ─────────────────────────────────────

  subheader("Phase 2: 30-Cycle Training Loop");
  console.log();

  const TOTAL_ROUNDS = 30;
  const BUDGET = 300; // tight budget forces trade-offs
  const qualityHistory: number[] = [];

  for (let turn = 1; turn <= TOTAL_ROUNDS; turn++) {
    const items = generateSupportItems(turn);
    const result = await optimizer.pack(items, { maxTokens: BUDGET });
    const quality = simulateQuality(result.selected, turn);

    await optimizer.reportOutcome(result.optimizerId, {
      quality,
      accepted: quality > 0.6,
      response: `Simulated response for turn ${turn}`,
    });

    qualityHistory.push(quality);

    // Print progress every 5 rounds
    if (turn % 5 === 0 || turn === 1) {
      const avgRecent =
        qualityHistory.slice(-5).reduce((a, b) => a + b, 0) /
        Math.min(5, qualityHistory.length);
      const selectedKinds = result.selected.map(i => i.kind).join(", ");
      console.log(
        `  ${DIM}Turn ${String(turn).padStart(2)}${RESET}  ` +
          `quality ${bar(quality, 15)} ${(quality * 100).toFixed(0)}%  ` +
          `${DIM}avg(5): ${(avgRecent * 100).toFixed(0)}%  ` +
          `[${selectedKinds}]${RESET}`
      );
    }
  }

  // ─── Phase 3: Analyse Insights ──────────────────────────────────

  subheader("Phase 3: Learned Insights");

  const insights = await optimizer.getInsights();

  console.log();
  console.log(`  ${BOLD}Current Weights (after learning):${RESET}`);
  metric("Priority", fmtWeight(insights.currentWeights.priority));
  metric("Recency", fmtWeight(insights.currentWeights.recency));
  metric("Salience", fmtWeight(insights.currentWeights.salience));
  metric("Relevance", fmtWeight(insights.currentWeights.relevance ?? 1));

  console.log();
  console.log(`  ${BOLD}Recommended Weights:${RESET}`);
  metric("Priority", fmtWeight(insights.recommendedWeights.priority));
  metric("Recency", fmtWeight(insights.recommendedWeights.recency));
  metric("Salience", fmtWeight(insights.recommendedWeights.salience));
  metric("Relevance", fmtWeight(insights.recommendedWeights.relevance ?? 1));

  console.log();
  console.log(`  ${BOLD}Correlations (feature vs. quality):${RESET}`);
  metric("Priority <-> quality", insights.correlations.priority.toFixed(3));
  metric("Recency <-> quality", insights.correlations.recency.toFixed(3));
  metric("Salience <-> quality", insights.correlations.salience.toFixed(3));
  metric("Relevance <-> quality", insights.correlations.relevance.toFixed(3));

  console.log();
  metric("Sample count", insights.sampleCount);
  metric(
    "Confidence",
    `${(insights.confidence * 100).toFixed(1)}%`,
    insights.confidence > 0.5 ? GREEN : YELLOW
  );

  // ─── Phase 4: Kind Insights ─────────────────────────────────────

  if (insights.kindInsights.length > 0) {
    subheader("Phase 4: Per-Kind Impact Analysis");
    console.log();

    const maxKindLen = Math.max(
      ...insights.kindInsights.map(k => k.kind.length),
      4
    );
    console.log(
      `  ${DIM}${"Kind".padEnd(maxKindLen)}  Included  Excluded   Lift  Count${RESET}`
    );

    for (const ki of insights.kindInsights) {
      const liftColor =
        ki.inclusionLift > 0 ? GREEN : ki.inclusionLift < 0 ? RED : WHITE;
      const liftStr =
        ki.inclusionLift >= 0
          ? `+${ki.inclusionLift.toFixed(3)}`
          : ki.inclusionLift.toFixed(3);
      console.log(
        `  ${WHITE}${ki.kind.padEnd(maxKindLen)}${RESET}  ` +
          `${(ki.avgQualityWhenIncluded * 100).toFixed(1).padStart(7)}%  ` +
          `${(ki.avgQualityWhenExcluded * 100).toFixed(1).padStart(7)}%  ` +
          `${liftColor}${liftStr.padStart(6)}${RESET}  ` +
          `${String(ki.count).padStart(5)}`
      );
    }

    console.log();
    console.log(
      `  ${DIM}"Lift" = quality(included) - quality(excluded).${RESET}`
    );
    console.log(
      `  ${DIM}Positive lift means including that kind improves responses.${RESET}`
    );
  }

  // ─── Phase 5: Before vs After Comparison ────────────────────────

  subheader("Phase 5: Before vs After — Same Items, Different Weights");
  console.log();

  const testItems = generateSupportItems(99);

  // Pack with original equal weights
  const beforePack = pack(testItems, {
    maxTokens: BUDGET,
  });

  // Pack with learned weights
  const afterPack = await optimizer.pack(testItems, { maxTokens: BUDGET });

  console.log(`  ${CYAN}Before (equal weights):${RESET}`);
  for (const item of beforePack.selected) {
    console.log(
      `    ${item.id.padEnd(22)} ${DIM}kind=${item.kind}, recency=${item.recency ?? "?"}${RESET}`
    );
  }

  console.log();
  console.log(`  ${GREEN}After (learned weights):${RESET}`);
  for (const item of afterPack.selected) {
    console.log(
      `    ${item.id.padEnd(22)} ${DIM}kind=${item.kind}, recency=${item.recency ?? "?"}${RESET}`
    );
  }

  const beforeQuality = simulateQuality(beforePack.selected, 99);
  const afterQuality = simulateQuality(afterPack.selected, 99);
  const improvement = ((afterQuality - beforeQuality) / beforeQuality) * 100;

  console.log();
  metric("Before quality", `${(beforeQuality * 100).toFixed(1)}%`);
  metric(
    "After quality",
    `${(afterQuality * 100).toFixed(1)}%`,
    afterQuality > beforeQuality ? GREEN : RED
  );
  metric(
    "Improvement",
    `${improvement >= 0 ? "+" : ""}${improvement.toFixed(1)}%`,
    improvement > 0 ? GREEN : RED
  );

  // ─── Phase 6: State Export/Import ───────────────────────────────

  subheader("Phase 6: Persist and Restore Optimizer State");
  console.log();

  const state = await optimizer.exportState();
  console.log(`  ${DIM}Exported state:${RESET}`);
  metric("Segment", state.segment);
  metric("Sample count", state.sampleCount);
  metric("Exported at", new Date(state.exportedAt).toISOString());

  // Import into a fresh optimizer
  const freshOptimizer = createContextOptimizer({ feedback: "explicit" });
  await freshOptimizer.importState(state);
  const restoredInsights = await freshOptimizer.getInsights();

  console.log();
  console.log(`  ${GREEN}Restored into fresh optimizer:${RESET}`);
  metric(
    "Priority weight",
    fmtWeight(restoredInsights.currentWeights.priority)
  );
  metric("Recency weight", fmtWeight(restoredInsights.currentWeights.recency));
  metric(
    "Salience weight",
    fmtWeight(restoredInsights.currentWeights.salience)
  );
  console.log(
    `\n  ${DIM}Learned weights survive restarts — use FileFeedbackStore for disk persistence.${RESET}`
  );

  // ─── Summary ────────────────────────────────────────────────────

  header("Summary");

  console.log("  The Adaptive Optimizer:");
  console.log(
    `    ${GREEN}1.${RESET} Starts with equal (or custom) base weights`
  );
  console.log(
    `    ${GREEN}2.${RESET} Records which items are selected and what quality results`
  );
  console.log(
    `    ${GREEN}3.${RESET} Computes Pearson correlations between features and outcomes`
  );
  console.log(
    `    ${GREEN}4.${RESET} Shifts weights toward dimensions that correlate with quality`
  );
  console.log(
    `    ${GREEN}5.${RESET} Reports per-kind impact so you know which content types help`
  );
  console.log(
    `    ${GREEN}6.${RESET} Exports/imports state for production persistence`
  );
  console.log();
  console.log(
    `  ${DIM}See packages/ce-adaptive/ for FileFeedbackStore (disk) and segment isolation.${RESET}\n`
  );
}

main().catch(console.error);
