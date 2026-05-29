import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchBudgetRecommendation,
  fetchWeightConfig,
  recommendationOptionsFromEnv,
} from "./recommendations.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Budget Recommendation
// ---------------------------------------------------------------------------

describe("fetchBudgetRecommendation", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    // Clear env vars so they don't leak between tests
    delete process.env.CE_BUDGET_URL;
    delete process.env.CE_WEIGHTS_URL;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns fallback budget when no URL configured", async () => {
    const rec = await fetchBudgetRecommendation("sess-1");

    expect(rec.maxTokens).toBe(128_000);
    expect(rec.confidence).toBe(0);
    expect(rec.source).toBe("default");
    expect(rec.reason).toContain("No recommendation source");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("returns custom fallback budget when specified", async () => {
    const rec = await fetchBudgetRecommendation("sess-1", {
      fallbackBudget: 64_000,
    });

    expect(rec.maxTokens).toBe(64_000);
  });

  it("returns fallback budget on fetch failure", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network error"));

    const rec = await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://example.com/budget",
    });

    expect(rec.maxTokens).toBe(128_000);
    expect(rec.confidence).toBe(0);
    expect(rec.source).toBe("default");
  });

  it("returns fallback budget on timeout", async () => {
    vi.mocked(fetch).mockImplementationOnce(
      () =>
        new Promise((_, reject) => {
          setTimeout(() => reject(new Error("aborted")), 50);
        })
    );

    const rec = await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://example.com/budget",
      timeoutMs: 10,
    });

    expect(rec.maxTokens).toBe(128_000);
    expect(rec.source).toBe("default");
  });

  it("returns fallback budget on non-OK response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response("Not Found", { status: 404 })
    );

    const rec = await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://example.com/budget",
    });

    expect(rec.maxTokens).toBe(128_000);
    expect(rec.source).toBe("default");
  });

  it("returns recommendation from valid response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        maxTokens: 96_000,
        reserveTokens: 4_000,
        confidence: 0.85,
        source: "make.com",
        reason: "Based on recent usage patterns",
      })
    );

    const rec = await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://example.com/budget",
    });

    expect(rec.maxTokens).toBe(96_000);
    expect(rec.reserveTokens).toBe(4_000);
    expect(rec.confidence).toBe(0.85);
    expect(rec.source).toBe("make.com");
    expect(rec.reason).toBe("Based on recent usage patterns");
  });

  it("clamps confidence to 0-1", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ maxTokens: 50_000, confidence: 1.5 })
    );

    const rec = await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://example.com/budget",
    });

    expect(rec.confidence).toBe(1);
  });

  it("rejects negative reserveTokens (returns undefined)", async () => {
    // Regression: a misbehaving endpoint returning a negative reserveTokens
    // used to be passed through, producing a recommendation that throws a
    // ValidationError downstream in pack() — defeating the fail-safe contract.
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ maxTokens: 50_000, reserveTokens: -5_000 })
    );

    const rec = await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://example.com/budget",
    });

    expect(rec.maxTokens).toBe(50_000);
    expect(rec.reserveTokens).toBeUndefined();
  });

  it("reads budget URL from env var", async () => {
    process.env.CE_BUDGET_URL = "https://env.example.com/budget";
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ maxTokens: 80_000, confidence: 0.6, source: "env" })
    );

    const rec = await fetchBudgetRecommendation("sess-1");

    expect(fetch).toHaveBeenCalledOnce();
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toContain("https://env.example.com/budget");
    expect(rec.maxTokens).toBe(80_000);
  });

  it("explicit URL overrides env var", async () => {
    process.env.CE_BUDGET_URL = "https://env.example.com/budget";
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ maxTokens: 70_000, confidence: 0.9 })
    );

    const rec = await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://explicit.example.com/budget",
    });

    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toContain("https://explicit.example.com/budget");
    expect(calledUrl).not.toContain("env.example.com");
    expect(rec.maxTokens).toBe(70_000);
  });

  it("handles malformed JSON gracefully", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response("not json at all", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const rec = await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://example.com/budget",
    });

    expect(rec.maxTokens).toBe(128_000);
    expect(rec.source).toBe("default");
  });

  it("appends sessionId as query parameter", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ maxTokens: 50_000, confidence: 0.5 })
    );

    await fetchBudgetRecommendation("my-session", {
      budgetUrl: "https://example.com/budget",
    });

    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toContain("sessionId=my-session");
  });

  it("uses & separator when URL already has query params", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ maxTokens: 50_000, confidence: 0.5 })
    );

    await fetchBudgetRecommendation("my-session", {
      budgetUrl: "https://example.com/budget?key=val",
    });

    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toBe(
      "https://example.com/budget?key=val&sessionId=my-session"
    );
  });

  it("sends custom headers", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ maxTokens: 50_000, confidence: 0.5 })
    );

    await fetchBudgetRecommendation("sess-1", {
      budgetUrl: "https://example.com/budget",
      headers: { Authorization: "Bearer test-token" },
    });

    const calledOptions = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(
      (calledOptions.headers as Record<string, string>).Authorization
    ).toBe("Bearer test-token");
  });
});

// ---------------------------------------------------------------------------
// Weight Config
// ---------------------------------------------------------------------------

describe("fetchWeightConfig", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    delete process.env.CE_BUDGET_URL;
    delete process.env.CE_WEIGHTS_URL;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns fallback weights when no URL configured", async () => {
    const config = await fetchWeightConfig("sess-1");

    expect(config.id).toBe("default");
    expect(config.priority).toBe(1.0);
    expect(config.recency).toBe(0.7);
    expect(config.salience).toBe(0.5);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("returns custom fallback weights when specified", async () => {
    const config = await fetchWeightConfig("sess-1", {
      fallbackWeights: { priority: 2.0, recency: 0.5, salience: 0.3 },
    });

    expect(config.priority).toBe(2.0);
    expect(config.recency).toBe(0.5);
    expect(config.salience).toBe(0.3);
  });

  it("returns weight config from valid response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        id: "experiment-42",
        priority: 1.5,
        recency: 0.3,
        salience: 0.8,
        metadata: { variant: "B" },
      })
    );

    const config = await fetchWeightConfig("sess-1", {
      weightsUrl: "https://example.com/weights",
    });

    expect(config.id).toBe("experiment-42");
    expect(config.priority).toBe(1.5);
    expect(config.recency).toBe(0.3);
    expect(config.salience).toBe(0.8);
    expect(config.metadata).toEqual({ variant: "B" });
  });

  it("returns fallback on fetch failure", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network error"));

    const config = await fetchWeightConfig("sess-1", {
      weightsUrl: "https://example.com/weights",
    });

    expect(config.id).toBe("default");
    expect(config.priority).toBe(1.0);
    expect(config.recency).toBe(0.7);
    expect(config.salience).toBe(0.5);
  });

  it("handles malformed JSON gracefully", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response("{invalid", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const config = await fetchWeightConfig("sess-1", {
      weightsUrl: "https://example.com/weights",
    });

    expect(config.id).toBe("default");
    expect(config.priority).toBe(1.0);
  });

  it("reads weights URL from env var", async () => {
    process.env.CE_WEIGHTS_URL = "https://env.example.com/weights";
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        id: "env-config",
        priority: 2.0,
        recency: 0.1,
        salience: 0.9,
      })
    );

    const config = await fetchWeightConfig("sess-1");

    expect(fetch).toHaveBeenCalledOnce();
    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toContain("https://env.example.com/weights");
    expect(config.id).toBe("env-config");
  });

  it("explicit URL overrides env var", async () => {
    process.env.CE_WEIGHTS_URL = "https://env.example.com/weights";
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        id: "explicit-config",
        priority: 1.2,
        recency: 0.6,
        salience: 0.4,
      })
    );

    const config = await fetchWeightConfig("sess-1", {
      weightsUrl: "https://explicit.example.com/weights",
    });

    const calledUrl = vi.mocked(fetch).mock.calls[0][0] as string;
    expect(calledUrl).toContain("https://explicit.example.com/weights");
    expect(config.id).toBe("explicit-config");
  });
});

// ---------------------------------------------------------------------------
// recommendationOptionsFromEnv
// ---------------------------------------------------------------------------

describe("recommendationOptionsFromEnv", () => {
  beforeEach(() => {
    delete process.env.CE_BUDGET_URL;
    delete process.env.CE_WEIGHTS_URL;
  });

  afterEach(() => {
    delete process.env.CE_BUDGET_URL;
    delete process.env.CE_WEIGHTS_URL;
  });

  it("reads env vars", () => {
    process.env.CE_BUDGET_URL = "https://budget.example.com";
    process.env.CE_WEIGHTS_URL = "https://weights.example.com";

    const opts = recommendationOptionsFromEnv();

    expect(opts.budgetUrl).toBe("https://budget.example.com");
    expect(opts.weightsUrl).toBe("https://weights.example.com");
  });

  it("returns undefined for missing env vars", () => {
    const opts = recommendationOptionsFromEnv();

    expect(opts.budgetUrl).toBeUndefined();
    expect(opts.weightsUrl).toBeUndefined();
  });
});
