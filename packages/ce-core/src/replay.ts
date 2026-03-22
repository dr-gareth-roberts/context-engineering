import { pack } from "./pack.js";
import type { ContextPack } from "./types.js";
import type {
  ContextRecording,
  ReplayVariant,
  ReplayResult,
  VariantSummary,
  ReplayReport,
} from "./replay-types.js";

/**
 * Replay recorded context packing decisions with different strategies.
 *
 * Takes a set of recordings and a list of variant strategies, re-runs
 * pack() with each variant's options, and produces a comparison report.
 *
 * @example
 * ```ts
 * const report = replay(recorder.getRecordings(), [
 *   { name: 'baseline' },
 *   { name: 'recency-heavy', options: { weights: { priority: 0.5, recency: 2.0 } } },
 *   { name: 'tight-budget', budget: { maxTokens: 2048 } },
 * ]);
 *
 * report.variants.forEach(v => {
 *   console.log(`${v.name}: avg ${v.avgTokenDelta} token delta, ${v.avgUtilization}% util`);
 * });
 * ```
 */
export function replay(
  recordings: readonly ContextRecording[],
  variants: ReplayVariant[]
): ReplayReport {
  const variantSummaries: VariantSummary[] = variants.map((variant) => {
    const results: ReplayResult[] = [];

    for (const recording of recordings) {
      const budget = variant.budget ?? recording.budget;
      const options = {
        ...recording.options,
        ...variant.options,
      };

      let newPack: ContextPack;
      try {
        newPack = pack(recording.items, budget, options);
      } catch {
        // If pack fails with this variant, skip
        continue;
      }

      const originalSelectedIds = new Set(
        recording.result.selected.map((i) => i.id)
      );
      const newSelectedIds = new Set(newPack.selected.map((i) => i.id));

      const newlySelected = [...newSelectedIds].filter(
        (id) => !originalSelectedIds.has(id)
      );
      const newlyDropped = [...originalSelectedIds].filter(
        (id) => !newSelectedIds.has(id)
      );

      results.push({
        recordingId: recording.id,
        variantName: variant.name,
        pack: newPack,
        tokenDelta: newPack.totalTokens - recording.result.totalTokens,
        selectionChanges: { newlySelected, newlyDropped },
      });
    }

    const avgTokenDelta =
      results.length > 0
        ? results.reduce((sum, r) => sum + r.tokenDelta, 0) / results.length
        : 0;

    const avgUtilization =
      results.length > 0
        ? results.reduce((sum, r) => {
            const budget = r.pack.budget.maxTokens;
            return sum + (budget > 0 ? (r.pack.totalTokens / budget) * 100 : 0);
          }, 0) / results.length
        : 0;

    const recordingsAffected = results.filter(
      (r) =>
        r.selectionChanges.newlySelected.length > 0 ||
        r.selectionChanges.newlyDropped.length > 0
    ).length;

    return {
      name: variant.name,
      results,
      avgTokenDelta: Math.round(avgTokenDelta * 100) / 100,
      avgUtilization: Math.round(avgUtilization * 100) / 100,
      recordingsAffected,
    };
  });

  return {
    timestamp: new Date().toISOString(),
    recordingCount: recordings.length,
    variants: variantSummaries,
  };
}
