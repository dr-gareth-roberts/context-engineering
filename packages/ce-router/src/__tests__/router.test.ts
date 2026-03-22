import { describe, it, expect } from "vitest";
import { createContextRouter } from "../router.js";
import type { ContextItem } from "@context-engineering/core";
import type { ModelTier, RouterConfig } from "../types.js";

function makeItem(
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem {
  return { id, content, ...overrides };
}

const cheapModel: ModelTier = {
  model: "gpt-4.1-mini",
  maxComplexity: 0.5,
  costPer1kInput: 0.0004,
  costPer1kOutput: 0.0016,
  maxTokens: 16000,
};

const midModel: ModelTier = {
  model: "gpt-4.1",
  maxComplexity: 0.6,
  costPer1kInput: 0.002,
  costPer1kOutput: 0.008,
  maxTokens: 128000,
  capabilities: ["tool-calling"],
};

const expensiveModel: ModelTier = {
  model: "claude-opus-4-6",
  maxComplexity: 1.0,
  costPer1kInput: 0.015,
  costPer1kOutput: 0.075,
  maxTokens: 200000,
  capabilities: ["tool-calling", "vision"],
};

const threeModelConfig: RouterConfig = {
  models: [cheapModel, midModel, expensiveModel],
};

describe("createContextRouter", () => {
  it("routes simple context to the cheapest model", () => {
    const router = createContextRouter(threeModelConfig);
    const items = [makeItem("a", "hello world")];
    const decision = router.route(items, { maxTokens: 4000 });

    expect(decision.model).toBe("gpt-4.1-mini");
    expect(decision.complexity).toBeLessThan(0.5);
  });

  it("routes complex context to a more capable model", () => {
    // Use a config that weights tool calls and dependency depth heavily
    const config: RouterConfig = {
      models: [{ ...cheapModel, maxComplexity: 0.3 }, midModel, expensiveModel],
      complexityWeights: {
        toolCallCount: 0.4,
        dependencyDepth: 0.4,
        diversity: 0.05,
        density: 0.05,
        multilinguality: 0.05,
        averageItemLength: 0.05,
      },
    };
    const router = createContextRouter(config);
    const longContent = "complex analysis required ".repeat(500);
    const items = [
      makeItem("a", longContent, { kind: "tool_call" }),
      makeItem("b", longContent, { kind: "tool_result", dependsOn: ["a"] }),
      makeItem("c", longContent, { kind: "tool_call", dependsOn: ["b"] }),
      makeItem("d", longContent, { kind: "tool_result", dependsOn: ["c"] }),
      makeItem("e", longContent, { kind: "tool_call", dependsOn: ["d"] }),
    ];
    const decision = router.route(items, { maxTokens: 4000 });

    // High tool call count (1.0) and dependency depth (0.4) should push past 0.3
    expect(decision.complexity).toBeGreaterThan(0.3);
    expect(decision.model).not.toBe("gpt-4.1-mini");
  });

  it("falls back to default when no model qualifies", () => {
    const config: RouterConfig = {
      models: [cheapModel, midModel],
      defaultModel: "gpt-4.1",
    };
    const router = createContextRouter(config);

    // Request tokens exceeding both models
    const items = [makeItem("a", "test")];
    const decision = router.route(items, { maxTokens: 200000 });

    expect(decision.model).toBe("gpt-4.1");
    expect(decision.reasoning).toContain("fallback");
  });

  it("respects maxTokens constraint and skips models with insufficient context window", () => {
    const router = createContextRouter(threeModelConfig);
    const items = [makeItem("a", "simple query")];

    // Budget larger than cheapModel's maxTokens (16000) and midModel's (128000)
    const decision = router.route(items, { maxTokens: 150000 });

    expect(decision.model).toBe("claude-opus-4-6");
  });

  it("respects requiredCapabilities and skips models without needed capabilities", () => {
    const router = createContextRouter(threeModelConfig);
    const items = [makeItem("a", "analyze this image")];
    const decision = router.route(
      items,
      { maxTokens: 4000 },
      {
        requiredCapabilities: ["vision"],
      }
    );

    // Only expensiveModel has 'vision'
    expect(decision.model).toBe("claude-opus-4-6");
  });

  it("returns correct cost estimates for the selected model", () => {
    const router = createContextRouter(threeModelConfig);
    const items = [makeItem("a", "hello")];
    const decision = router.route(items, { maxTokens: 4000 });

    expect(decision.estimatedCost.inputCostPer1k).toBe(
      cheapModel.costPer1kInput
    );
    expect(decision.estimatedCost.outputCostPer1k).toBe(
      cheapModel.costPer1kOutput
    );
  });

  it("includes alternative model and cost delta", () => {
    const router = createContextRouter(threeModelConfig);
    const items = [makeItem("a", "hello")];
    const decision = router.route(items, { maxTokens: 4000 });

    expect(decision.alternativeModel).toBe("gpt-4.1");
    expect(decision.alternativeCostDelta).toBeGreaterThan(0);
  });

  it("builds a reasoning string that explains the routing decision", () => {
    const router = createContextRouter(threeModelConfig);
    const items = [makeItem("a", "hello")];
    const decision = router.route(items, { maxTokens: 4000 });

    expect(decision.reasoning).toContain("gpt-4.1-mini");
    expect(decision.reasoning).toContain("complexity");
    expect(decision.reasoning).toContain("cheapest qualifying model");
  });

  it("handles single-model config by always routing to that model", () => {
    const config: RouterConfig = {
      models: [midModel],
    };
    const router = createContextRouter(config);
    const items = [makeItem("a", "hello")];
    const decision = router.route(items, { maxTokens: 4000 });

    expect(decision.model).toBe("gpt-4.1");
    expect(decision.alternativeModel).toBeUndefined();
  });

  it("uses the most capable model as fallback when no defaultModel is set", () => {
    const config: RouterConfig = {
      models: [cheapModel, expensiveModel],
    };
    const router = createContextRouter(config);
    const items = [makeItem("a", "test")];

    // Budget exceeds both models
    const decision = router.route(items, { maxTokens: 999999 });

    expect(decision.model).toBe("claude-opus-4-6");
    expect(decision.reasoning).toContain("most capable");
  });
});
