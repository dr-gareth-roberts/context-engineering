import { describe, it, expect } from "vitest";
import { createAdaptiveRouter } from "../adaptive-router.js";
import type { ContextItem } from "@context-engineering/core";
import type {
  AdaptiveRouterConfig,
  ModelTier,
  RoutingDecision,
} from "../types.js";

function makeItem(
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem {
  return { id, content, ...overrides };
}

const cheapModel: ModelTier = {
  model: "cheap-model",
  maxComplexity: 0.5,
  costPer1kInput: 0.001,
  costPer1kOutput: 0.002,
  maxTokens: 16000,
};

const midModel: ModelTier = {
  model: "mid-model",
  maxComplexity: 0.8,
  costPer1kInput: 0.005,
  costPer1kOutput: 0.01,
  maxTokens: 128000,
};

const expensiveModel: ModelTier = {
  model: "expensive-model",
  maxComplexity: 1.0,
  costPer1kInput: 0.015,
  costPer1kOutput: 0.075,
  maxTokens: 200000,
};

const defaultConfig: AdaptiveRouterConfig = {
  models: [cheapModel, midModel, expensiveModel],
  minSamples: 5,
};

describe("createAdaptiveRouter", () => {
  it("routes same as base router before minSamples is reached", () => {
    const router = createAdaptiveRouter(defaultConfig);
    const items = [makeItem("a", "hello world")];
    const decision = router.route(items, { maxTokens: 4000 });

    expect(decision.model).toBe("cheap-model");
  });

  it("returns correct stats from getInsights after reporting outcomes", () => {
    const router = createAdaptiveRouter(defaultConfig);
    const items = [makeItem("a", "hello world")];
    const decision = router.route(items, { maxTokens: 4000 });

    router.reportOutcome(decision, 0.9);
    router.reportOutcome(decision, 0.8);

    const insights = router.getInsights();
    expect(insights.totalDecisions).toBe(2);
    expect(insights.modelStats["cheap-model"].uses).toBe(2);
    expect(insights.modelStats["cheap-model"].avgQuality).toBeCloseTo(0.85, 1);
  });

  it("promotes to higher tier after sufficient low-quality outcomes", () => {
    const router = createAdaptiveRouter({ ...defaultConfig, minSamples: 3 });
    const items = [makeItem("a", "hello world")];

    // Report several poor-quality outcomes for cheap model at low complexity
    for (let i = 0; i < 5; i++) {
      const decision = router.route(items, { maxTokens: 4000 });
      router.reportOutcome(decision, 0.2); // poor quality
    }

    // Now with enough samples showing poor quality, should promote
    const decision = router.route(items, { maxTokens: 4000 });
    expect(decision.model).toBe("mid-model");
    expect(decision.reasoning).toContain("promoted");
  });

  it("stores outcomes correctly via reportOutcome", () => {
    const router = createAdaptiveRouter(defaultConfig);
    const items = [makeItem("a", "test content")];
    const decision = router.route(items, { maxTokens: 4000 });

    router.reportOutcome(decision, 0.75);
    router.reportOutcome(decision, 0.65);
    router.reportOutcome(decision, 0.85);

    const insights = router.getInsights();
    expect(insights.totalDecisions).toBe(3);
    expect(insights.modelStats["cheap-model"].avgQuality).toBeCloseTo(0.75, 1);
  });

  it("computes potentialSavings correctly", () => {
    const router = createAdaptiveRouter({ ...defaultConfig, minSamples: 100 });
    const items = [makeItem("a", "hello world")];

    // Simulate outcomes for both cheap and mid models
    const cheapDecision: RoutingDecision = {
      model: "cheap-model",
      complexity: 0.2,
      complexityBreakdown: {
        overall: 0.2,
        dimensions: {
          diversity: 0.1,
          density: 0.1,
          dependencyDepth: 0,
          toolCallCount: 0,
          multilinguality: 0,
          averageItemLength: 0.1,
        },
      },
      reasoning: "test",
      estimatedCost: { inputCostPer1k: 0.001, outputCostPer1k: 0.002 },
    };

    const midDecision: RoutingDecision = {
      ...cheapDecision,
      model: "mid-model",
      estimatedCost: { inputCostPer1k: 0.005, outputCostPer1k: 0.01 },
    };

    // Report good quality for cheap model
    router.reportOutcome(cheapDecision, 0.9);
    router.reportOutcome(cheapDecision, 0.8);

    // Report outcomes for mid model at similar complexity
    router.reportOutcome(midDecision, 0.85);
    router.reportOutcome(midDecision, 0.9);

    const insights = router.getInsights();
    // Mid model outcomes could have used cheap model (which has good quality)
    expect(insights.potentialSavings).toBeGreaterThan(0);
  });

  it("handles multiple model tiers with different quality histories", () => {
    const router = createAdaptiveRouter({ ...defaultConfig, minSamples: 3 });
    const simpleItems = [makeItem("a", "simple")];

    // First fill up outcomes with low quality for cheap model
    for (let i = 0; i < 4; i++) {
      const d = router.route(simpleItems, { maxTokens: 4000 });
      router.reportOutcome(d, 0.3);
    }

    // Now routing should promote to mid model
    const promotedDecision = router.route(simpleItems, { maxTokens: 4000 });
    expect(promotedDecision.model).toBe("mid-model");

    // Report good quality for mid model
    router.reportOutcome(promotedDecision, 0.9);
    router.reportOutcome(promotedDecision, 0.85);

    const insights = router.getInsights();
    expect(insights.modelStats["cheap-model"]).toBeDefined();
    expect(insights.modelStats["mid-model"]).toBeDefined();
    expect(insights.modelStats["mid-model"].avgQuality).toBeGreaterThan(
      insights.modelStats["cheap-model"].avgQuality
    );
  });
});
