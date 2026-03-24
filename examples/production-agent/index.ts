/**
 * Production Agent with Drift Monitoring, Immune System, and Time Travel
 *
 * Simulates a 20-turn agent conversation where context gradually degrades.
 * Demonstrates how drift detection catches quality drops and how time travel
 * enables recovery to a known-good state. The immune system learns from
 * failures and screens future context packs.
 *
 * Run: npx tsx examples/production-agent/index.ts
 */

import type { ContextItem, Budget } from "@context-engineering/core";
import { analyzeContext, pack } from "@context-engineering/core";
import type {
  DriftReport,
  DriftDimension,
  DriftSeverity,
} from "@context-engineering/drift";
import { createDriftMonitor } from "@context-engineering/drift";
import { createTimeline } from "@context-engineering/time-travel";
import { createImmuneSystem } from "@context-engineering/immune";
import { createAdversarialTester } from "@context-engineering/adversarial";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

const SEVERITY_ICON: Record<DriftSeverity, string> = {
  healthy: "[OK]",
  warning: "[!!]",
  critical: "[XX]",
};

function sparkline(values: number[], width = 20): string {
  if (values.length === 0) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const bars = " _.,:-=!#";
  return values
    .slice(-width)
    .map(v => {
      const idx = Math.min(
        bars.length - 1,
        Math.round(((v - min) / range) * (bars.length - 1))
      );
      return bars[idx];
    })
    .join("");
}

function pad(s: string, n: number): string {
  return s.padEnd(n);
}

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function printBanner(text: string): void {
  const line = "=".repeat(70);
  console.log(`\n${line}`);
  console.log(`  ${text}`);
  console.log(line);
}

function printSection(text: string): void {
  console.log(`\n--- ${text} ${"─".repeat(Math.max(0, 60 - text.length))}`);
}

function printDriftSummary(report: DriftReport): void {
  const dims: DriftDimension[] = [
    "relevance",
    "redundancy",
    "diversity",
    "density",
    "freshness",
    "utilization",
  ];
  for (const dim of dims) {
    const d = report.dimensions[dim];
    const icon = SEVERITY_ICON[d.severity];
    const trend =
      d.trend === "improving"
        ? "(up)"
        : d.trend === "degrading"
          ? "(dn)"
          : "(..)";
    const spark = sparkline(d.history);
    console.log(
      `    ${icon} ${pad(dim, 14)} ${fmtPct(d.current).padStart(7)} ` +
        `(baseline ${fmtPct(d.baseline).padStart(7)}, delta ${d.delta >= 0 ? "+" : ""}${d.delta.toFixed(3)}) ` +
        `${trend} |${spark}|`
    );
  }
}

// ---------------------------------------------------------------------------
// Context item factories — realistic content for a coding agent
// ---------------------------------------------------------------------------

function systemPromptItem(): ContextItem {
  return {
    id: "system-prompt",
    content:
      "You are a senior TypeScript engineer. Follow these rules:\n" +
      "1. Use strict TypeScript with explicit return types.\n" +
      "2. Prefer functional composition over class hierarchies.\n" +
      "3. All public APIs must have JSDoc comments.\n" +
      "4. Handle errors explicitly — no silent catches.\n" +
      "5. Write tests for every public function.",
    kind: "system",
    priority: 10,
    recency: 10,
  };
}

function apiDocItem(name: string, recency: number): ContextItem {
  const docs: Record<string, string> = {
    "auth-api":
      "POST /api/auth/login — Accepts { email, password }. Returns { token, refreshToken, expiresIn }. Requires Content-Type: application/json. Rate limited to 5 req/min per IP.",
    "user-api":
      "GET /api/users/:id — Returns { id, name, email, role, createdAt }. Requires Authorization: Bearer <token>. Returns 404 if user not found, 403 if insufficient permissions.",
    "webhook-api":
      "POST /api/webhooks — Register a webhook. Body: { url, events: string[], secret? }. Returns { id, status }. Webhooks receive POST with HMAC-SHA256 signature in X-Signature header.",
    "search-api":
      "GET /api/search?q=term&limit=20&offset=0 — Full-text search across documents. Returns { results: Array<{ id, title, snippet, score }>, total, hasMore }.",
    "config-api":
      "GET /api/config — Returns application configuration. Includes feature flags, rate limits, and environment-specific overrides. Cached for 5 minutes.",
  };
  return {
    id: `doc-${name}`,
    content: docs[name] ?? `Documentation for ${name} endpoint.`,
    kind: "documentation",
    priority: 7,
    recency,
  };
}

function conversationTurn(
  turnNum: number,
  role: "user" | "assistant",
  content: string,
  recency: number
): ContextItem {
  return {
    id: `turn-${turnNum}`,
    content: `[Turn ${turnNum}] ${role}: ${content}`,
    kind: "conversation",
    priority: 6,
    recency,
  };
}

function codeSnippetItem(
  name: string,
  code: string,
  recency: number
): ContextItem {
  return {
    id: `code-${name}`,
    content: code,
    kind: "code",
    priority: 8,
    recency,
  };
}

function staleDocItem(idx: number): ContextItem {
  const staleDocs = [
    "The legacy XML-RPC endpoint at /api/v1/rpc has been deprecated since 2019. It accepted SOAP-formatted requests and returned XML. Migration guide available at /docs/migration.",
    'jQuery plugin integration: Include jquery.min.js before loading the SDK. Call $.contextPlugin({ apiKey: "..." }) to initialize. Note: jQuery 1.x is no longer supported.',
    "Flash-based file upload component: Set the SWF path in config.flashUrl. Requires Flash Player 10+. Note: Adobe discontinued Flash support in December 2020.",
    "Internet Explorer 8 compatibility: Add the following polyfills to support IE8 — es5-shim, json3, html5shiv. Set X-UA-Compatible meta tag to edge mode.",
    "FTP deployment guide: Upload dist/ contents to your server via FTP. Set permissions to 755 for directories, 644 for files. Restart Apache with apachectl restart.",
    'CVS version control integration: Run cvs checkout module-name to get the latest code. Commit changes with cvs commit -m "message". See CVS manual for branching.',
  ];
  return {
    id: `stale-doc-${idx}`,
    content: staleDocs[idx % staleDocs.length],
    kind: "documentation",
    priority: 2 + (idx % 3),
    recency: 0.1,
  };
}

function redundantDocItem(baseContent: string, variant: number): ContextItem {
  const prefixes = [
    "As previously mentioned, ",
    "To reiterate the earlier point, ",
    "Repeating for clarity: ",
    "As stated above, ",
    "Once more, note that ",
  ];
  return {
    id: `redundant-${variant}`,
    content: prefixes[variant % prefixes.length] + baseContent.toLowerCase(),
    kind: "documentation",
    priority: 3 + (variant % 3),
    recency: 4 + (variant % 3),
  };
}

function noiseItem(idx: number): ContextItem {
  const noise = [
    "Meeting notes from Q3 planning: Discussed headcount, budget allocation for cloud infrastructure, and timeline for the marketing site redesign. Action items assigned to Sarah and Mike.",
    "Team standup summary: Backend team blocked on database migration. Frontend team shipped the dark mode toggle. DevOps investigating intermittent 503 errors in staging.",
    "HR announcement: New PTO policy takes effect next quarter. All unused days roll over up to 5 days maximum. Mandatory training on workplace safety due by end of month.",
    "Lunch menu for the week: Monday — grilled chicken. Tuesday — pasta primavera. Wednesday — fish tacos. Thursday — vegetable stir-fry. Friday — build your own burger.",
    "Office maintenance notice: The elevators on floors 3-5 will be serviced this weekend. Please use the stairs or the freight elevator on the north side of the building.",
    "Company all-hands recap: Revenue grew 12% QoQ. Three new enterprise customers signed. Engineering headcount increasing by 8 positions. Holiday party scheduled for December 15.",
    "Parking lot update: Construction on the new parking structure begins next Monday. Temporary parking available at the overflow lot on Elm Street. Shuttle service provided.",
    "IT helpdesk FAQ: Reset your password at sso.company.com/reset. VPN issues? Try disconnecting and reconnecting. For hardware requests, submit a ticket in ServiceNow.",
  ];
  return {
    id: `noise-${idx}`,
    content: noise[idx % noise.length],
    kind: "documentation",
    priority: 1 + Math.random() * 2,
    recency: 1 + Math.random() * 3,
  };
}

// ---------------------------------------------------------------------------
// Main simulation
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  printBanner(
    "Production Agent — Drift Monitoring, Immune System, Time Travel"
  );
  console.log(
    "Simulating a 20-turn agent conversation with gradual context degradation."
  );
  console.log(
    "Watch how the system detects drift, recovers, and learns from failures.\n"
  );

  // Budget: realistic 8K token window for a coding agent
  const budget: Budget = { maxTokens: 8000, reserveTokens: 500 };

  // Initialize the four subsystems
  const timeline = createTimeline({ defaultBranch: "main" });
  const monitor = createDriftMonitor({
    windowSize: 20,
    minObservations: 3,
    thresholds: {
      relevanceDrift: 0.15,
      redundancyCreep: 0.3,
      staleRatio: 0.35,
      topicDrift: 0.2,
      densityDrop: 0.2,
      underutilization: 0.4,
    },
  });
  const immune = createImmuneSystem({
    matchThreshold: 0.6,
  });

  // Track quality per turn for the final summary
  const turnQuality: Array<{
    turn: number;
    overall: number;
    status: DriftSeverity;
  }> = [];

  // =========================================================================
  // Phase 1: Setup (Turns 1-5) — Build a healthy context baseline
  // =========================================================================
  printBanner("Phase 1: Healthy Baseline (Turns 1-5)");

  const healthyItems: ContextItem[] = [
    systemPromptItem(),
    apiDocItem("auth-api", 9),
    apiDocItem("user-api", 8.5),
    apiDocItem("webhook-api", 8),
    codeSnippetItem(
      "auth-handler",
      [
        "async function handleLogin(req: Request): Promise<Response> {",
        "  const { email, password } = await req.json();",
        "  const user = await db.users.findByEmail(email);",
        "  if (!user || !await verify(password, user.hash)) {",
        '    return Response.json({ error: "Invalid credentials" }, { status: 401 });',
        "  }",
        "  const token = signJwt({ sub: user.id, role: user.role });",
        "  return Response.json({ token, expiresIn: 3600 });",
        "}",
      ].join("\n"),
      9
    ),
    conversationTurn(
      1,
      "user",
      "I need to add webhook signature verification to the auth flow.",
      10
    ),
    conversationTurn(
      2,
      "assistant",
      "I will add HMAC-SHA256 verification using the webhook secret. The signature will be checked in middleware before the handler runs.",
      9.5
    ),
    conversationTurn(
      3,
      "user",
      "Good. Also make sure we rate-limit the login endpoint — 5 requests per minute per IP.",
      9
    ),
    conversationTurn(
      4,
      "assistant",
      "I will use a sliding window rate limiter keyed on X-Forwarded-For. The limit is already documented as 5 req/min in the auth-api spec.",
      8.5
    ),
    conversationTurn(
      5,
      "user",
      "Perfect. Let us also add request logging with structured JSON output.",
      8
    ),
  ];

  timeline.setItems(healthyItems);

  for (let turn = 1; turn <= 5; turn++) {
    const items = timeline.getItems();
    monitor.observeItems(items, budget);
    const report = monitor.report();
    const quality = analyzeContext(items);
    turnQuality.push({ turn, overall: quality.overall, status: report.status });
    console.log(
      `  Turn ${turn}: ${items.length} items, quality=${quality.overall.toFixed(3)}, drift=${report.status}`
    );
  }

  // Checkpoint the healthy state
  timeline.checkpoint("healthy-baseline", {
    reason: "Initial healthy context established",
  });
  console.log('\n  >> Checkpoint saved: "healthy-baseline"');

  const baselineReport = monitor.report();
  printSection("Baseline Drift Report");
  printDriftSummary(baselineReport);

  // =========================================================================
  // Phase 2: Gradual Degradation (Turns 6-15) — Context quality decays
  // =========================================================================
  printBanner("Phase 2: Gradual Degradation (Turns 6-15)");
  console.log(
    "Each turn adds slightly worse context — stale docs, redundant items, noise.\n"
  );

  const authDocContent =
    "POST /api/auth/login requires email and password credentials for authentication";

  for (let turn = 6; turn <= 15; turn++) {
    const degradationLevel = (turn - 5) / 10; // 0.1 to 1.0

    // Add stale documentation items
    if (turn % 2 === 0) {
      const staleIdx = Math.floor((turn - 6) / 2);
      timeline.addItems(staleDocItem(staleIdx));
    }

    // Add redundant copies of existing docs
    if (turn >= 8 && turn % 3 === 0) {
      timeline.addItems(redundantDocItem(authDocContent, turn));
    }

    // Add noise items
    if (turn >= 10) {
      const noiseCount = Math.floor(degradationLevel * 3);
      for (let i = 0; i < noiseCount; i++) {
        timeline.addItems(noiseItem(turn * 10 + i));
      }
    }

    // Lower recency on older conversation turns to simulate time passing
    const items = timeline.getItems();
    const aged = items.map(item => {
      if (item.kind === "conversation" && (item.recency ?? 0) > 2) {
        return {
          ...item,
          recency: Math.max(0.5, (item.recency ?? 5) - degradationLevel * 2),
        };
      }
      return item;
    });
    timeline.setItems(aged);

    // Observe and report
    const currentItems = timeline.getItems();
    monitor.observeItems(currentItems, budget);
    const report = monitor.report();
    const quality = analyzeContext(currentItems);
    turnQuality.push({ turn, overall: quality.overall, status: report.status });

    const statusTag = SEVERITY_ICON[report.status];
    console.log(
      `  Turn ${turn}: ${statusTag} ${currentItems.length} items, ` +
        `quality=${quality.overall.toFixed(3)}, redundancy=${quality.redundancy.toFixed(3)}, ` +
        `freshness=${quality.freshness.toFixed(3)}, drift=${report.status}`
    );

    if (report.alerts.length > 0 && turn >= 8) {
      for (const alert of report.alerts.slice(0, 2)) {
        console.log(`         -> ${alert.message}`);
      }
    }
  }

  printSection("Drift Report at Turn 15");
  const degradedReport = monitor.report();
  printDriftSummary(degradedReport);

  if (degradedReport.alerts.length > 0) {
    console.log("\n  Alerts:");
    for (const alert of degradedReport.alerts) {
      console.log(`    - ${alert.message}`);
      console.log(`      Recommendation: ${alert.recommendation}`);
    }
  }

  // =========================================================================
  // Phase 3: Recovery via Time Travel (Turn 16)
  // =========================================================================
  printBanner("Phase 3: Drift Recovery via Time Travel (Turn 16)");

  const degradedItems = timeline.getItems();
  console.log(
    `  Current state: ${degradedItems.length} items, drift=${degradedReport.status}`
  );
  console.log(
    `  Drift has been active since observation #${degradedReport.since ? "detected" : "N/A"}`
  );
  console.log(`\n  >> Rewinding to checkpoint "healthy-baseline"...`);

  timeline.rewind("healthy-baseline");
  const rewindedItems = timeline.getItems();
  console.log(`  After rewind: ${rewindedItems.length} items`);

  // Add fresh, relevant items to replace what was lost
  const freshItems: ContextItem[] = [
    conversationTurn(
      16,
      "user",
      "After the refactor, can you show me the updated webhook verification code?",
      10
    ),
    codeSnippetItem(
      "webhook-verify",
      [
        "function verifyWebhookSignature(payload: string, signature: string, secret: string): boolean {",
        '  const expected = createHmac("sha256", secret).update(payload).digest("hex");',
        "  return timingSafeEqual(Buffer.from(signature), Buffer.from(expected));",
        "}",
      ].join("\n"),
      10
    ),
    apiDocItem("search-api", 9),
  ];

  timeline.addItems(...freshItems);
  timeline.checkpoint("recovered", {
    reason: "Recovered from drift via time travel + fresh context",
  });

  // Reset the monitor to re-establish baseline from the recovered state
  monitor.reset();
  const recoveredItems = timeline.getItems();
  monitor.observeItems(recoveredItems, budget);
  const recoveredReport = monitor.report();
  const recoveredQuality = analyzeContext(recoveredItems);

  turnQuality.push({
    turn: 16,
    overall: recoveredQuality.overall,
    status: recoveredReport.status,
  });

  console.log(
    `\n  Recovered: ${recoveredItems.length} items, ` +
      `quality=${recoveredQuality.overall.toFixed(3)}, drift=${recoveredReport.status}`
  );

  printSection("Post-Recovery Drift Report");
  printDriftSummary(recoveredReport);

  // =========================================================================
  // Phase 4: Adversarial Testing (Turns 17-18)
  // =========================================================================
  printBanner("Phase 4: Adversarial Stress Test (Turns 17-18)");

  const tester = createAdversarialTester({
    attacks: [
      { type: "contradiction", intensity: 0.4 },
      { type: "noise-flood", intensity: 0.3 },
      { type: "subtle-error", intensity: 0.5 },
      { type: "authority-spoof", intensity: 0.3 },
      { type: "temporal-poison", intensity: 0.4 },
      { type: "relevance-dilution", intensity: 0.2 },
    ],
    probeRounds: 2,
  });

  // Quality evaluator: uses the built-in analyzeContext heuristic
  const evaluator = async (packed: ContextItem[]): Promise<number> => {
    const q = analyzeContext(packed);
    return q.overall;
  };

  console.log("  Running adversarial probes against recovered context...\n");

  const probeItems = timeline.getItems();
  const probeReport = await tester.probe(probeItems, budget, evaluator);

  console.log(`  Overall resilience: ${probeReport.overall.toUpperCase()}`);
  console.log(
    `  Baseline quality:   ${probeReport.baselineQuality.toFixed(3)}`
  );
  console.log(`  Total probes:       ${probeReport.totalProbes}`);
  console.log(`  Duration:           ${probeReport.durationMs}ms\n`);

  console.log("  Attack Results:");
  console.log("  " + "-".repeat(66));
  console.log(
    `  ${pad("Attack", 22)} ${pad("Baseline", 10)} ${pad("Attacked", 10)} ` +
      `${pad("Drop", 8)} ${pad("Severity", 12)}`
  );
  console.log("  " + "-".repeat(66));

  for (const attack of probeReport.attacks) {
    const severityTag =
      attack.severity === "critical"
        ? "[CRITICAL]"
        : attack.severity === "vulnerable"
          ? "[VULN]    "
          : "[OK]      ";
    console.log(
      `  ${pad(attack.attack, 22)} ${attack.baselineQuality.toFixed(3).padStart(8)}   ` +
        `${attack.attackedQuality.toFixed(3).padStart(8)}   ` +
        `${(attack.qualityDrop >= 0 ? "-" : "+") + Math.abs(attack.qualityDrop).toFixed(3).padStart(5)}  ` +
        `${severityTag}`
    );
  }

  // Record the worst vulnerability in the immune system
  turnQuality.push({
    turn: 17,
    overall: probeReport.baselineQuality,
    status: "healthy",
  });
  turnQuality.push({
    turn: 18,
    overall: probeReport.baselineQuality,
    status: "healthy",
  });

  if (
    probeReport.worstAttack &&
    probeReport.worstAttack.severity !== "resilient"
  ) {
    printSection("Recording worst vulnerability as immune system antibody");

    // Build a degraded item set that mimics the worst attack pattern
    const worstType = probeReport.worstAttack.attack;
    console.log(
      `  Worst attack: ${worstType} (quality drop: ${probeReport.worstAttack.qualityDrop.toFixed(3)})`
    );

    // Record the failure pattern so the immune system can recognize it
    const antibody = immune.recordFailure({
      items: probeItems,
      budget,
      symptom: `Quality degradation from ${worstType} attack`,
      diagnosis: `Pipeline vulnerable to ${worstType}: quality dropped ${probeReport.worstAttack.qualityDrop.toFixed(3)} from baseline`,
      severity:
        probeReport.worstAttack.severity === "critical" ? "block" : "warning",
    });

    console.log(`  Antibody created: ${antibody.id}`);
    console.log(`  Severity: ${antibody.severity}`);
    console.log(`  Diagnosis: ${antibody.diagnosis}`);
  }

  // =========================================================================
  // Phase 5: Immune Screening (Turns 19-20)
  // =========================================================================
  printBanner("Phase 5: Immune System Screening (Turns 19-20)");

  // Turn 19: Screen the current healthy context — should pass
  console.log("  Turn 19: Screening current healthy context...");
  const healthyScreen = immune.screen(timeline.getItems(), budget);
  console.log(`    Safe: ${healthyScreen.safe}`);
  console.log(`    Warnings: ${healthyScreen.warnings.length}`);
  console.log(`    Blocked: ${healthyScreen.blocked.length}`);
  console.log(`    Antibodies fired: ${healthyScreen.antibodiesFired.length}`);

  if (healthyScreen.antibodiesFired.length > 0) {
    console.log("\n    Antibody matches on healthy context:");
    for (const ab of healthyScreen.antibodiesFired) {
      const alert = [...healthyScreen.warnings, ...healthyScreen.blocked].find(
        a => a.antibodyId === ab.id
      );
      console.log(
        `      - ${ab.id}: similarity=${alert?.similarity.toFixed(3) ?? "N/A"}, ` +
          `severity=${ab.severity}`
      );
      console.log(`        Symptom: ${ab.symptom}`);
    }
  }

  turnQuality.push({
    turn: 19,
    overall: analyzeContext(timeline.getItems()).overall,
    status: "healthy",
  });

  // Turn 20: Create a context that resembles the failure pattern
  printSection("Turn 20: Testing with degraded context");
  console.log(
    "  Packing context that resembles the previously failed pattern...\n"
  );

  // Rebuild a degraded item set similar to what caused the failure
  const degradedTestItems: ContextItem[] = [
    ...timeline.getItems(),
    staleDocItem(10),
    staleDocItem(11),
    staleDocItem(12),
    redundantDocItem(authDocContent, 20),
    redundantDocItem(authDocContent, 21),
    noiseItem(200),
    noiseItem(201),
    noiseItem(202),
  ];

  const degradedScreen = immune.screen(degradedTestItems, budget);
  console.log(`  Safe: ${degradedScreen.safe}`);
  console.log(`  Warnings: ${degradedScreen.warnings.length}`);
  console.log(`  Blocked: ${degradedScreen.blocked.length}`);
  console.log(`  Antibodies fired: ${degradedScreen.antibodiesFired.length}`);

  if (degradedScreen.antibodiesFired.length > 0) {
    console.log("\n  Immune system response:");
    for (const ab of degradedScreen.antibodiesFired) {
      const alert = [
        ...degradedScreen.warnings,
        ...degradedScreen.blocked,
      ].find(a => a.antibodyId === ab.id);
      console.log(
        `    Antibody ${ab.id} FIRED (similarity: ${alert?.similarity.toFixed(3) ?? "N/A"})`
      );
      console.log(`      Symptom:   ${ab.symptom}`);
      console.log(`      Diagnosis: ${ab.diagnosis}`);
      console.log(`      Severity:  ${ab.severity}`);
    }
  } else {
    console.log(
      "\n  No antibodies fired — pattern did not match closely enough."
    );
  }

  const degradedTestQuality = analyzeContext(degradedTestItems);
  turnQuality.push({
    turn: 20,
    overall: degradedTestQuality.overall,
    status: degradedScreen.safe ? "healthy" : "warning",
  });

  // =========================================================================
  // Final Summary
  // =========================================================================
  printBanner("Final Summary");

  // Turn-by-turn quality timeline
  console.log("  Turn-by-turn quality:");
  console.log("  " + "-".repeat(60));
  const maxBarWidth = 30;
  for (const t of turnQuality) {
    const barLen = Math.round(t.overall * maxBarWidth);
    const bar = "#".repeat(barLen) + ".".repeat(maxBarWidth - barLen);
    const tag = SEVERITY_ICON[t.status];
    console.log(
      `  Turn ${String(t.turn).padStart(2)}: ${tag} ${t.overall.toFixed(3)} |${bar}|`
    );
  }

  // Key events
  printSection("Key Events");

  const driftTurn = turnQuality.find(t => t.status !== "healthy");
  if (driftTurn) {
    console.log(
      `  Drift first detected at Turn ${driftTurn.turn} (status: ${driftTurn.status})`
    );
  }
  console.log(
    '  Recovery via time travel at Turn 16 (rewind to "healthy-baseline")'
  );
  console.log(
    `  Adversarial test at Turns 17-18: overall resilience = ${probeReport.overall}`
  );

  const antibodies = immune.getAntibodies();
  console.log(`  Immune system antibodies learned: ${antibodies.length}`);
  for (const ab of antibodies) {
    console.log(`    - ${ab.id}: ${ab.symptom} [${ab.severity}]`);
  }

  // Timeline history
  printSection("Timeline History");
  const snapshots = timeline.history();
  for (const snap of snapshots) {
    const label = snap.name.startsWith("auto:")
      ? snap.name
      : `** ${snap.name} **`;
    console.log(`  ${label} — ${snap.items.length} items`);
  }

  console.log(
    "\n  Branches:",
    timeline
      .listBranches()
      .map(b => b.name)
      .join(", ")
  );
  console.log(`  Current branch: ${timeline.currentBranch()}`);

  console.log("\n" + "=".repeat(70));
  console.log("  Simulation complete.");
  console.log("=".repeat(70) + "\n");
}

main().catch(err => {
  console.error("Simulation failed:", err);
  process.exit(1);
});
