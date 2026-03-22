import type { ScoringWeights } from "@context-engineering/core";
import type { FeedbackRecord, WeightInsights } from "./types.js";

const WEIGHT_MIN = 0.01;
const WEIGHT_MAX = 10.0;
const SCORING_DIMENSIONS = [
  "priority",
  "recency",
  "salience",
  "relevance",
] as const;
export interface WeightOptimizerConfig {
  learningRate: number;
  regularization: number;
  baseWeights: ScoringWeights;
  minSamples: number;
}

/**
 * Computes optimal scoring weights from feedback records using
 * correlation analysis with exponential moving average updates.
 */
export class WeightOptimizer {
  private config: WeightOptimizerConfig;

  constructor(config: WeightOptimizerConfig) {
    this.config = config;
  }

  /**
   * Compute optimal weights from feedback records.
   * Returns base weights if insufficient samples.
   */
  optimize(records: FeedbackRecord[]): ScoringWeights {
    const withOutcomes = records.filter(r => r.outcome !== undefined);

    if (withOutcomes.length < this.config.minSamples) {
      return { ...this.config.baseWeights };
    }

    const correlations = this.computeCorrelations(withOutcomes);
    const currentWeights = { ...this.config.baseWeights };
    const lr = this.config.learningRate;
    const reg = this.config.regularization;

    for (const dim of SCORING_DIMENSIONS) {
      const baseWeight = this.config.baseWeights[dim] ?? 1.0;
      const current = currentWeights[dim] ?? 1.0;
      const signal = correlations[dim] ?? 0;

      // EMA update: blend current weight toward base + correlation signal
      let updated = (1 - lr) * current + lr * (baseWeight + signal);

      // L2 regularization: pull toward base weights
      updated -= reg * (updated - baseWeight);

      // Clamp to prevent collapse or explosion
      currentWeights[dim] = clamp(updated, WEIGHT_MIN, WEIGHT_MAX);
    }

    return currentWeights;
  }

  /**
   * Compute Pearson correlation between each scoring dimension
   * of selected items and the outcome quality score.
   */
  computeCorrelations(records: FeedbackRecord[]): Record<string, number> {
    const withOutcomes = records.filter(r => r.outcome !== undefined);

    if (withOutcomes.length < 2) {
      return Object.fromEntries(SCORING_DIMENSIONS.map(d => [d, 0]));
    }

    const result: Record<string, number> = {};

    for (const dim of SCORING_DIMENSIONS) {
      const pairs: Array<{ dimValue: number; quality: number }> = [];

      for (const record of withOutcomes) {
        const selectedFeatures = record.itemFeatures.filter(f => f.selected);
        if (selectedFeatures.length === 0) continue;

        // Average dimension value across selected items
        const avgDim = mean(selectedFeatures.map(f => f[dim]));
        pairs.push({ dimValue: avgDim, quality: record.outcome?.quality ?? 0 });
      }

      result[dim] =
        pairs.length >= 2
          ? pearsonCorrelation(
              pairs.map(p => p.dimValue),
              pairs.map(p => p.quality)
            )
          : 0;
    }

    return result;
  }

  /**
   * Compute per-kind insights: which item kinds correlate with quality.
   */
  computeKindInsights(
    records: FeedbackRecord[]
  ): WeightInsights["kindInsights"] {
    const withOutcomes = records.filter(r => r.outcome !== undefined);

    if (withOutcomes.length === 0) {
      return [];
    }

    // Collect all unique kinds
    const allKinds = new Set<string>();
    for (const record of withOutcomes) {
      for (const feature of record.itemFeatures) {
        allKinds.add(feature.kind);
      }
    }

    const insights: WeightInsights["kindInsights"] = [];

    for (const kind of allKinds) {
      const qualityWhenIncluded: number[] = [];
      const qualityWhenExcluded: number[] = [];

      for (const record of withOutcomes) {
        const quality = record.outcome?.quality ?? 0;
        const hasKindSelected = record.itemFeatures.some(
          f => f.kind === kind && f.selected
        );

        if (hasKindSelected) {
          qualityWhenIncluded.push(quality);
        } else {
          qualityWhenExcluded.push(quality);
        }
      }

      const avgIncluded =
        qualityWhenIncluded.length > 0 ? mean(qualityWhenIncluded) : 0;
      const avgExcluded =
        qualityWhenExcluded.length > 0 ? mean(qualityWhenExcluded) : 0;

      insights.push({
        kind,
        avgQualityWhenIncluded: avgIncluded,
        avgQualityWhenExcluded: avgExcluded,
        inclusionLift: avgIncluded - avgExcluded,
        count: qualityWhenIncluded.length + qualityWhenExcluded.length,
      });
    }

    return insights.sort((a, b) => b.inclusionLift - a.inclusionLift);
  }

  /**
   * Compute confidence based on sample size and quality variance.
   * Returns 0-1 where higher means more reliable insights.
   */
  computeConfidence(records: FeedbackRecord[]): number {
    const withOutcomes = records.filter(r => r.outcome !== undefined);

    if (withOutcomes.length === 0) {
      return 0;
    }

    // Sample size factor: sigmoid-like curve, approaches 1 as samples grow
    const sampleFactor = 1 - Math.exp(-withOutcomes.length / 50);

    // Variance factor: low variance in quality means less signal to learn from,
    // but also high variance might mean noise. Medium variance is best.
    const qualities = withOutcomes.map(r => r.outcome?.quality ?? 0);
    const qualityVariance = variance(qualities);

    // Optimal variance is around 0.04-0.1 (std dev 0.2-0.3)
    // Too low (< 0.01) = no signal, too high (> 0.25) = noisy
    const varianceFactor =
      qualityVariance < 0.01
        ? qualityVariance / 0.01
        : qualityVariance > 0.25
          ? Math.max(0, 1 - (qualityVariance - 0.25) / 0.25)
          : 1;

    return clamp(sampleFactor * varianceFactor, 0, 1);
  }
}

/** Compute arithmetic mean of an array. Returns 0 for empty arrays. */
function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

/** Compute population variance. Returns 0 for arrays with fewer than 2 elements. */
function variance(values: number[]): number {
  if (values.length < 2) return 0;
  const m = mean(values);
  return values.reduce((sum, v) => sum + (v - m) ** 2, 0) / values.length;
}

/**
 * Compute Pearson correlation coefficient between two arrays.
 * Returns 0 if either array has zero variance.
 */
function pearsonCorrelation(xs: number[], ys: number[]): number {
  const n = xs.length;
  if (n < 2) return 0;

  const xMean = mean(xs);
  const yMean = mean(ys);

  let numerator = 0;
  let xSumSq = 0;
  let ySumSq = 0;

  for (let i = 0; i < n; i++) {
    const dx = xs[i] - xMean;
    const dy = ys[i] - yMean;
    numerator += dx * dy;
    xSumSq += dx * dx;
    ySumSq += dy * dy;
  }

  const denominator = Math.sqrt(xSumSq * ySumSq);
  if (denominator === 0) return 0;

  return numerator / denominator;
}

/** Clamp a value between min and max. */
function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
