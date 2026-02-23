import { ContextItem, Budget, ContextTrace, PackOptions } from "./types";
import { internalPack } from "./pack";

/**
 * Pack items with a decision trace for debugging and observability.
 *
 * Same algorithm as pack() but records every selection decision
 * (include, exclude, compress) with reasons.
 *
 * @param items - Context items to pack
 * @param budget - Token budget
 * @param options - Packing options
 * @returns A ContextTrace with pack result and step-by-step decisions
 *
 * @example
 * ```ts
 * const trace = tracePack(items, { maxTokens: 4096 });
 * trace.steps.forEach(s => console.log(`${s.id}: ${s.decision}`));
 * ```
 */
export function tracePack(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {}
): ContextTrace {
  const { pack, steps } = internalPack(items, budget, options, true);

  return {
    pack,
    steps: steps ?? [],
    createdAt: new Date().toISOString(),
  };
}
