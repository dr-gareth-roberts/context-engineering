import type { ContextItem, Budget } from "@context-engineering/core";
import { createContextRouter } from "./router.js";
import type {
  AdaptiveRouter,
  AdaptiveRouterConfig,
  RouteOptions,
  RouterInsights,
  RoutingDecision,
} from "./types.js";

interface Outcome {
  model: string;
  complexity: number;
  quality: number;
}

/**
 * Create an adaptive router that learns from past outcomes.
 *
 * Wraps a base context router and adjusts routing decisions based on
 * observed quality scores. If a model consistently underperforms for
 * a given complexity range, the router promotes to the next tier.
 */
export function createAdaptiveRouter(
  config: AdaptiveRouterConfig
): AdaptiveRouter {
  const baseRouter = createContextRouter(config);
  const outcomes: Outcome[] = [];
  const minSamples = config.minSamples ?? 20;
  const sortedModels = [...config.models].sort(
    (a, b) => a.costPer1kInput - b.costPer1kInput
  );

  return {
    route(
      items: ContextItem[],
      budget: Budget,
      options?: RouteOptions
    ): RoutingDecision {
      const baseDecision = baseRouter.route(items, budget, options);

      // Only adjust if we have enough data
      if (outcomes.length < minSamples) {
        return baseDecision;
      }

      // Check average quality for the chosen model at similar complexity
      const complexityRange = 0.15;
      const relevantOutcomes = outcomes.filter(
        o =>
          o.model === baseDecision.model &&
          Math.abs(o.complexity - baseDecision.complexity) <= complexityRange
      );

      if (relevantOutcomes.length === 0) {
        return baseDecision;
      }

      const avgQuality =
        relevantOutcomes.reduce((sum, o) => sum + o.quality, 0) /
        relevantOutcomes.length;

      // If quality is poor, promote to next tier
      if (avgQuality < 0.5) {
        const currentIndex = sortedModels.findIndex(
          m => m.model === baseDecision.model
        );
        if (currentIndex >= 0 && currentIndex < sortedModels.length - 1) {
          const promoted = sortedModels[currentIndex + 1];
          return {
            ...baseDecision,
            model: promoted.model,
            reasoning: `${promoted.model}: promoted from ${baseDecision.model} due to low avg quality (${avgQuality.toFixed(2)}) at complexity ${baseDecision.complexity.toFixed(2)}`,
            estimatedCost: {
              inputCostPer1k: promoted.costPer1kInput,
              outputCostPer1k: promoted.costPer1kOutput,
            },
            alternativeModel: baseDecision.model,
            alternativeCostDelta:
              Math.round(
                (baseDecision.estimatedCost.inputCostPer1k -
                  promoted.costPer1kInput) *
                  10000
              ) / 10000,
          };
        }
      }

      return baseDecision;
    },

    reportOutcome(decision: RoutingDecision, quality: number): void {
      outcomes.push({
        model: decision.model,
        complexity: decision.complexity,
        quality,
      });
    },

    getInsights(): RouterInsights {
      const modelStats: RouterInsights["modelStats"] = {};

      for (const outcome of outcomes) {
        if (!modelStats[outcome.model]) {
          modelStats[outcome.model] = {
            uses: 0,
            avgQuality: 0,
            avgComplexity: 0,
          };
        }
        const stats = modelStats[outcome.model];
        stats.uses++;
        stats.avgQuality += outcome.quality;
        stats.avgComplexity += outcome.complexity;
      }

      // Finalize averages
      for (const stats of Object.values(modelStats)) {
        if (stats.uses > 0) {
          stats.avgQuality =
            Math.round((stats.avgQuality / stats.uses) * 1000) / 1000;
          stats.avgComplexity =
            Math.round((stats.avgComplexity / stats.uses) * 1000) / 1000;
        }
      }

      // Compute potential savings: for each outcome, check if a cheaper model
      // has good avg quality at that complexity range
      let potentialSavings = 0;
      for (const outcome of outcomes) {
        const currentTier = sortedModels.find(m => m.model === outcome.model);
        if (!currentTier) continue;

        // Check cheaper models
        for (const cheaperModel of sortedModels) {
          if (cheaperModel.costPer1kInput >= currentTier.costPer1kInput) break;

          const cheaperOutcomes = outcomes.filter(
            o =>
              o.model === cheaperModel.model &&
              Math.abs(o.complexity - outcome.complexity) <= 0.15
          );

          if (cheaperOutcomes.length > 0) {
            const cheaperAvgQuality =
              cheaperOutcomes.reduce((s, o) => s + o.quality, 0) /
              cheaperOutcomes.length;

            if (cheaperAvgQuality >= 0.5) {
              potentialSavings +=
                currentTier.costPer1kInput - cheaperModel.costPer1kInput;
              break;
            }
          }
        }
      }

      return {
        totalDecisions: outcomes.length,
        modelStats,
        potentialSavings: Math.round(potentialSavings * 10000) / 10000,
      };
    },
  };
}
