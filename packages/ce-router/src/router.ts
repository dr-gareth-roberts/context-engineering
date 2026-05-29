import type { ContextItem, Budget } from "@context-engineering/core";
import { analyzeComplexity } from "./complexity.js";
import type {
  ContextRouter,
  ModelTier,
  RouterConfig,
  RouteOptions,
  RoutingDecision,
} from "./types.js";

/**
 * Create a context router that analyzes complexity and picks the cheapest
 * model capable of handling the request.
 *
 * Models are sorted by input cost ascending — the router always prefers
 * the cheapest qualifying option.
 */
export function createContextRouter(config: RouterConfig): ContextRouter {
  if (config.models.length === 0) {
    throw new Error("RouterConfig.models must contain at least one model");
  }
  const sortedModels = [...config.models].sort(
    (a, b) => a.costPer1kInput - b.costPer1kInput
  );

  return {
    route(
      items: ContextItem[],
      budget: Budget,
      options?: RouteOptions
    ): RoutingDecision {
      const complexity = analyzeComplexity(items, config.complexityWeights);

      const requiredCaps = options?.requiredCapabilities ?? [];

      // Find cheapest qualifying model
      const selected = sortedModels.find(model => {
        if (model.maxComplexity < complexity.overall) return false;
        if (model.maxTokens < budget.maxTokens) return false;
        if (requiredCaps.length > 0) {
          const modelCaps = model.capabilities ?? [];
          if (!requiredCaps.every(cap => modelCaps.includes(cap))) return false;
        }
        return true;
      });

      // Fallback: default model or most capable (last in sorted = most expensive)
      const fallback = config.defaultModel
        ? (sortedModels.find(m => m.model === config.defaultModel) ??
          sortedModels[sortedModels.length - 1])
        : sortedModels[sortedModels.length - 1];

      const chosen: ModelTier = selected ?? fallback;

      // Find alternative: next tier up from chosen
      const chosenIndex = sortedModels.indexOf(chosen);
      const alternative =
        chosenIndex < sortedModels.length - 1
          ? sortedModels[chosenIndex + 1]
          : undefined;

      const reasoning = selected
        ? `${chosen.model}: complexity ${complexity.overall.toFixed(2)} within threshold ${chosen.maxComplexity}, cheapest qualifying model`
        : `${chosen.model}: no model met all constraints, using ${config.defaultModel ? "default" : "most capable"} fallback`;

      const decision: RoutingDecision = {
        model: chosen.model,
        complexity: complexity.overall,
        complexityBreakdown: complexity,
        reasoning,
        estimatedCost: {
          inputCostPer1k: chosen.costPer1kInput,
          outputCostPer1k: chosen.costPer1kOutput,
        },
      };

      if (alternative) {
        decision.alternativeModel = alternative.model;
        decision.alternativeCostDelta =
          Math.round(
            (alternative.costPer1kInput - chosen.costPer1kInput) * 10000
          ) / 10000;
      }

      return decision;
    },
  };
}
