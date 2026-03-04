import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  createWebhookReporter,
  noopReporter,
} from "./webhook.js";
import type {
  WebhookAnalyticsPayload,
  WebhookHandoffPayload,
} from "./webhook.js";
import type { ContextPack, ContextTrace } from "./types.js";
import type { HandoffResult } from "./beads.js";

function makePack(overrides?: Partial<ContextPack>): ContextPack {
  return {
    budget: { maxTokens: 4096 },
    selected: [
      { id: "a", content: "hello", tokens: 100 },
      { id: "b", content: "world", tokens: 200 },
    ],
    dropped: [{ id: "c", content: "dropped", tokens: 500 }],
    totalTokens: 300,
    ...overrides,
  };
}

function makeTrace(): ContextTrace {
  return {
    pack: makePack(),
    steps: [
      { id: "a", decision: "include", tokens: 100, reason: "fits_budget" },
      { id: "b", decision: "include", tokens: 200, reason: "fits_budget" },
      { id: "c", decision: "exclude", tokens: 500, reason: "over_budget" },
    ],
    createdAt: "2026-01-01T00:00:00.000Z",
  };
}

function makeHandoff(): HandoffResult {
  return {
    jsonl: '{"id":"ce-handoff-test"}\n{"id":"ce-a"}',
    issues: [],
    stats: {
      totalIssues: 2,
      contextIssues: 1,
      activeItems: 1,
      deferredItems: 0,
    },
  };
}

let fetchSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchSpy = vi.fn().mockResolvedValue(new Response("ok", { status: 200 }));
  vi.stubGlobal("fetch", fetchSpy);
  // Clear env vars
  delete process.env.CE_WEBHOOK_URL;
  delete process.env.CE_WEBHOOK_HANDOFF_URL;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("createWebhookReporter", () => {
  it("returns no-op when no URL configured", () => {
    const reporter = createWebhookReporter();
    reporter.reportPack(makePack());
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reads CE_WEBHOOK_URL from env", () => {
    process.env.CE_WEBHOOK_URL = "https://hook.example.com/analytics";
    const reporter = createWebhookReporter();
    reporter.reportPack(makePack());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe(
      "https://hook.example.com/analytics"
    );
  });

  it("reads CE_WEBHOOK_HANDOFF_URL from env", () => {
    process.env.CE_WEBHOOK_HANDOFF_URL = "https://hook.example.com/handoff";
    const reporter = createWebhookReporter();
    reporter.reportHandoff(makeHandoff());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe(
      "https://hook.example.com/handoff"
    );
  });

  it("prefers explicit URL over env var", () => {
    process.env.CE_WEBHOOK_URL = "https://env.example.com";
    const reporter = createWebhookReporter({
      analyticsUrl: "https://explicit.example.com",
    });
    reporter.reportPack(makePack());
    expect(fetchSpy.mock.calls[0][0]).toBe("https://explicit.example.com");
  });
});

describe("reportPack", () => {
  it("sends correct analytics payload shape", () => {
    const reporter = createWebhookReporter({
      analyticsUrl: "https://hook.example.com",
      sessionId: "test-session",
      model: "claude-sonnet-4-6",
      strategy: "greedy-score",
    });

    reporter.reportPack(makePack());

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const body = JSON.parse(
      fetchSpy.mock.calls[0][1].body
    ) as WebhookAnalyticsPayload;

    expect(body.event_type).toBe("pack");
    expect(body.session_id).toBe("test-session");
    expect(body.model).toBe("claude-sonnet-4-6");
    expect(body.strategy).toBe("greedy-score");
    expect(body.budget_max_tokens).toBe(4096);
    expect(body.budget_reserve_tokens).toBe(0);
    expect(body.total_tokens).toBe(300);
    expect(body.selected_count).toBe(2);
    expect(body.dropped_count).toBe(1);
    expect(body.remaining_tokens).toBe(3796);
    expect(body.timestamp).toBeTruthy();
  });

  it("computes budget_utilization_pct correctly", () => {
    const reporter = createWebhookReporter({
      analyticsUrl: "https://hook.example.com",
    });

    const pack = makePack({
      budget: { maxTokens: 1000, reserveTokens: 200 },
      totalTokens: 640,
    });
    reporter.reportPack(pack);

    const body = JSON.parse(
      fetchSpy.mock.calls[0][1].body
    ) as WebhookAnalyticsPayload;

    // 640 / (1000-200) = 640/800 = 80%
    expect(body.budget_utilization_pct).toBe(80);
  });

  it("includes quality and cost extras when provided", () => {
    const reporter = createWebhookReporter({
      analyticsUrl: "https://hook.example.com",
    });

    reporter.reportPack(makePack(), {
      quality: {
        itemCount: 2,
        totalTokens: 300,
        density: 0.8,
        diversity: 0.6,
        freshness: 0.9,
        redundancy: 0.1,
        overall: 0.75,
      },
      cost: {
        model: "claude-sonnet-4-6",
        inputTokens: 300,
        cachedTokens: 200,
        uncachedTokens: 100,
        outputTokens: 500,
        costWithoutCache: 0.02,
        costWithCache: 0.01,
        savings: 0.01,
        savingsPercent: 50,
        cacheEfficiency: 0.67,
      },
      cacheHitRatio: 0.67,
    });

    const body = JSON.parse(
      fetchSpy.mock.calls[0][1].body
    ) as WebhookAnalyticsPayload;

    expect(body.quality_overall).toBe(0.75);
    expect(body.quality_density).toBe(0.8);
    expect(body.quality_diversity).toBe(0.6);
    expect(body.cost_with_cache).toBe(0.01);
    expect(body.cost_without_cache).toBe(0.02);
    expect(body.cache_hit_ratio).toBe(0.67);
  });

  it("does not call fetch when analyticsUrl is empty", () => {
    const reporter = createWebhookReporter({
      handoffUrl: "https://hook.example.com/handoff",
    });
    reporter.reportPack(makePack());
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("reportTrace", () => {
  it("includes trace_decisions in payload", () => {
    const reporter = createWebhookReporter({
      analyticsUrl: "https://hook.example.com",
    });

    reporter.reportTrace(makeTrace());

    const body = JSON.parse(
      fetchSpy.mock.calls[0][1].body
    ) as WebhookAnalyticsPayload;

    expect(body.event_type).toBe("trace");
    expect(body.trace_decisions).toBeTruthy();

    const decisions = JSON.parse(body.trace_decisions!);
    expect(decisions).toHaveLength(3);
    expect(decisions[0]).toEqual({
      id: "a",
      decision: "include",
      tokens: 100,
      reason: "fits_budget",
    });
    expect(decisions[2]).toEqual({
      id: "c",
      decision: "exclude",
      tokens: 500,
      reason: "over_budget",
    });
  });
});

describe("reportHandoff", () => {
  it("sends to handoff URL with correct shape", () => {
    const reporter = createWebhookReporter({
      handoffUrl: "https://hook.example.com/handoff",
      sessionId: "sess-1",
    });

    reporter.reportHandoff(makeHandoff(), {
      sourceAgent: "agent-a",
      targetUrl: "https://target.example.com",
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe(
      "https://hook.example.com/handoff"
    );

    const body = JSON.parse(
      fetchSpy.mock.calls[0][1].body
    ) as WebhookHandoffPayload;

    expect(body.event_type).toBe("handoff");
    expect(body.session_id).toBe("sess-1");
    expect(body.total_issues).toBe(2);
    expect(body.active_items).toBe(1);
    expect(body.deferred_items).toBe(0);
    expect(body.source_agent).toBe("agent-a");
    expect(body.target_url).toBe("https://target.example.com");
    expect(body.jsonl_size_bytes).toBeGreaterThan(0);
  });

  it("does not call fetch when handoffUrl is empty", () => {
    const reporter = createWebhookReporter({
      analyticsUrl: "https://hook.example.com/analytics",
    });
    reporter.reportHandoff(makeHandoff());
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("error handling", () => {
  it("does not throw when fetch rejects", () => {
    fetchSpy.mockRejectedValue(new Error("network down"));
    const logger = {
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    };
    const reporter = createWebhookReporter({
      analyticsUrl: "https://hook.example.com",
      logger,
    });

    // Should not throw
    expect(() => reporter.reportPack(makePack())).not.toThrow();
  });

  it("logs warning on fetch failure", async () => {
    fetchSpy.mockRejectedValue(new Error("timeout"));
    const logger = {
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    };
    const reporter = createWebhookReporter({
      analyticsUrl: "https://hook.example.com",
      logger,
    });

    reporter.reportPack(makePack());

    // Wait for the promise rejection to propagate
    await vi.waitFor(() => {
      expect(logger.warn).toHaveBeenCalledWith("webhook:send_failed", {
        url: "https://hook.example.com",
        error: "timeout",
      });
    });
  });
});

describe("noopReporter", () => {
  it("makes no fetch calls", () => {
    noopReporter.reportPack(makePack());
    noopReporter.reportTrace(makeTrace());
    noopReporter.reportHandoff(makeHandoff());
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("custom headers", () => {
  it("sends custom headers with requests", () => {
    const reporter = createWebhookReporter({
      analyticsUrl: "https://hook.example.com",
      headers: { "X-API-Key": "secret-123" },
    });

    reporter.reportPack(makePack());

    const fetchOptions = fetchSpy.mock.calls[0][1];
    expect(fetchOptions.headers["X-API-Key"]).toBe("secret-123");
    expect(fetchOptions.headers["Content-Type"]).toBe("application/json");
  });
});
