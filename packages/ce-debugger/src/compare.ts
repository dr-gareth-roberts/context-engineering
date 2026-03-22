import type { ContextPack } from "@context-engineering/core";
import { analyzeContext } from "@context-engineering/core";
import type { ComparisonResult } from "./types.js";

export function compareResponses(
  packA: ContextPack,
  qualityA: number,
  packB: ContextPack,
  qualityB: number
): ComparisonResult {
  const packAQuality = analyzeContext(packA.selected);
  const packBQuality = analyzeContext(packB.selected);

  const idsA = new Set(packA.selected.map(i => i.id));
  const idsB = new Set(packB.selected.map(i => i.id));

  const onlyInA: string[] = [];
  const onlyInB: string[] = [];
  const shared: string[] = [];

  for (const id of idsA) {
    if (idsB.has(id)) {
      shared.push(id);
    } else {
      onlyInA.push(id);
    }
  }
  for (const id of idsB) {
    if (!idsA.has(id)) {
      onlyInB.push(id);
    }
  }

  const qualityDelta = qualityB - qualityA;

  const insights: string[] = [];

  if (qualityB > qualityA && onlyInB.length > 0) {
    insights.push(
      `Pack B included ${onlyInB.length} additional item(s) that may have improved response quality`
    );
  }

  if (qualityA > qualityB && onlyInB.length > 0) {
    insights.push(
      `Pack A produced better quality despite Pack B having ${onlyInB.length} additional item(s) — consider reducing noise`
    );
  }

  const redundancyDiff = Math.abs(
    packAQuality.redundancy - packBQuality.redundancy
  );
  if (redundancyDiff > 0.1) {
    const higher =
      packAQuality.redundancy > packBQuality.redundancy ? "A" : "B";
    insights.push(
      `Pack ${higher} has notably higher redundancy (${Math.round(redundancyDiff * 100)}% difference) — this may be diluting useful context`
    );
  }

  const utilA =
    packA.budget.maxTokens > 0 ? packA.totalTokens / packA.budget.maxTokens : 0;
  const utilB =
    packB.budget.maxTokens > 0 ? packB.totalTokens / packB.budget.maxTokens : 0;
  const utilDiff = Math.abs(utilA - utilB);
  if (utilDiff > 0.2) {
    const higher = utilA > utilB ? "A" : "B";
    insights.push(
      `Pack ${higher} has significantly higher budget utilization (${Math.round(utilDiff * 100)}% difference)`
    );
  }

  if (shared.length === 0 && (onlyInA.length > 0 || onlyInB.length > 0)) {
    insights.push(
      "Packs share no items — completely different context selections"
    );
  }

  if (onlyInA.length === 0 && onlyInB.length === 0 && shared.length > 0) {
    insights.push(
      "Packs contain identical items — quality difference is likely due to ordering or model variance"
    );
  }

  return {
    packAQuality,
    packBQuality,
    itemDiff: { onlyInA, onlyInB, shared },
    qualityDelta,
    insights,
  };
}
