import type { ContextItem, Budget } from "@context-engineering/core";
import type { ContextRouter, FallbackConfig, FallbackResult } from "./types.js";

/**
 * Route with quality-based fallback.
 *
 * Calls the primary (cheapest qualifying) model first. If quality is
 * below the threshold and an alternative model exists, retries with
 * the more capable model. This gives you cost savings on easy prompts
 * while preserving quality on hard ones.
 *
 * @param router - Context router to use for model selection
 * @param items - Context items to route
 * @param budget - Token budget constraints
 * @param callModel - Callback that executes the model call and returns the response
 * @param config - Fallback configuration with quality threshold and evaluator
 */
export async function routeWithFallback(
  router: ContextRouter,
  items: ContextItem[],
  budget: Budget,
  callModel: (model: string) => Promise<string>,
  config: FallbackConfig
): Promise<FallbackResult> {
  const decision = router.route(items, budget);
  const maxRetries = config.maxRetries ?? 1;

  // Call the primary model
  const primaryResponse = await callModel(decision.model);
  const primaryQuality = await config.qualityCallback(primaryResponse);

  // If quality is acceptable or no alternative exists, return primary result
  if (primaryQuality >= config.qualityThreshold || !decision.alternativeModel) {
    return {
      decision,
      finalModel: decision.model,
      attempts: 1,
      fellBack: false,
    };
  }

  // Try the alternative model(s)
  const currentModel = decision.alternativeModel;
  let attempts = 1;

  for (let retry = 0; retry < maxRetries; retry++) {
    attempts++;
    const fallbackResponse = await callModel(currentModel);
    const fallbackQuality = await config.qualityCallback(fallbackResponse);

    if (fallbackQuality >= config.qualityThreshold) {
      return {
        decision,
        finalModel: currentModel,
        attempts,
        fellBack: true,
      };
    }
  }

  // Exhausted retries — return whatever we ended up with
  return {
    decision,
    finalModel: currentModel,
    attempts,
    fellBack: true,
  };
}
