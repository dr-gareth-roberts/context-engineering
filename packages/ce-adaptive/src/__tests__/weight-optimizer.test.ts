import { describe, it, expect } from "vitest";
import { WeightOptimizer } from "../weight-optimizer.js";
import type { FeedbackRecord, Outcome } from "../types.js";
import type { ScoringWeights } from "@context-engineering/core";

const BASE_WEIGHTS: ScoringWeights = {
  priority: 1.0,
  recency: 1.0,
  salience: 1.0,
  relevance: 1.0,
};

function makeRecord(overrides: {
  quality: number;
  features?: Array<{
    priority?: number;
    recency?: number;
    salience?: number;
    relevance?: number;
    selected?: boolean;
  }>;
}): FeedbackRecord {
  const features = overrides.features ?? [
    { priority: 5, recency: 3, salience: 2, relevance: 4, selected: true },
  ];

  return {
    id: `rec_${Math.random().toString(36).slice(2)}`,
    timestamp: Date.now(),
    packId: `pack_${Math.random().toString(36).slice(2)}`,
    segment: "default",
    selectedItemIds: features
      .filter(f => f.selected !== false)
      .map((_, i) => `item_${i}`),
    droppedItemIds: features
      .filter(f => f.selected === false)
      .map((_, i) => `dropped_${i}`),
    itemFeatures: features.map((f, i) => ({
      itemId: f.selected !== false ? `item_${i}` : `dropped_${i}`,
      kind: "code",
      priority: f.priority ?? 0,
      recency: f.recency ?? 0,
      salience: f.salience ?? 0,
      relevance: f.relevance ?? 0,
      tokens: 100,
      selected: f.selected !== false,
    })),
    weightsUsed: { ...BASE_WEIGHTS },
    budget: 1000,
    utilization: 0.8,
    outcome: { quality: overrides.quality },
  };
}

function makeRecords(
  count: number,
  gen: (i: number) => Parameters<typeof makeRecord>[0]
): FeedbackRecord[] {
  return Array.from({ length: count }, (_, i) => makeRecord(gen(i)));
}

describe("WeightOptimizer", () => {
  const defaultConfig = {
    learningRate: 0.1,
    regularization: 0.01,
    baseWeights: { ...BASE_WEIGHTS },
    minSamples: 5,
  };

  describe("optimize", () => {
    it("returns base weights when below minSamples", () => {
      const optimizer = new WeightOptimizer({
        ...defaultConfig,
        minSamples: 10,
      });
      const records = makeRecords(5, () => ({ quality: 0.8 }));
      const result = optimizer.optimize(records);

      expect(result).toEqual(BASE_WEIGHTS);
    });

    it("returns base weights for empty records", () => {
      const optimizer = new WeightOptimizer(defaultConfig);
      const result = optimizer.optimize([]);

      expect(result).toEqual(BASE_WEIGHTS);
    });

    it("adjusts weights when sufficient samples exist", () => {
      const optimizer = new WeightOptimizer({
        ...defaultConfig,
        minSamples: 5,
      });

      // Create records where high priority correlates with high quality
      const records = makeRecords(20, i => ({
        quality: i / 20,
        features: [
          {
            priority: i,
            recency: 1,
            salience: 1,
            relevance: 1,
            selected: true,
          },
        ],
      }));

      const result = optimizer.optimize(records);

      // Priority should have shifted from base (correlation is positive)
      expect(result.priority).toBeDefined();
      // Other weights should also be defined
      expect(result.recency).toBeDefined();
      expect(result.salience).toBeDefined();
      expect(result.relevance).toBeDefined();
    });

    it("keeps weights clamped to valid range", () => {
      const optimizer = new WeightOptimizer({
        ...defaultConfig,
        learningRate: 0.99,
        regularization: 0,
        minSamples: 2,
      });

      const records = makeRecords(10, i => ({
        quality: i / 10,
        features: [
          {
            priority: i * 100,
            recency: 0,
            salience: 0,
            relevance: 0,
            selected: true,
          },
        ],
      }));

      const result = optimizer.optimize(records);

      // All weights should be within bounds
      for (const key of [
        "priority",
        "recency",
        "salience",
        "relevance",
      ] as const) {
        const w = result[key]!;
        expect(w).toBeGreaterThanOrEqual(0.01);
        expect(w).toBeLessThanOrEqual(10.0);
      }
    });

    it("learning rate controls adjustment speed", () => {
      const slowOptimizer = new WeightOptimizer({
        ...defaultConfig,
        learningRate: 0.01,
        minSamples: 2,
      });
      const fastOptimizer = new WeightOptimizer({
        ...defaultConfig,
        learningRate: 0.5,
        minSamples: 2,
      });

      const records = makeRecords(20, i => ({
        quality: i / 20,
        features: [
          {
            priority: i * 5,
            recency: 1,
            salience: 1,
            relevance: 1,
            selected: true,
          },
        ],
      }));

      const slowResult = slowOptimizer.optimize(records);
      const fastResult = fastOptimizer.optimize(records);

      // The fast optimizer should deviate more from base weights
      const slowDelta = Math.abs((slowResult.priority ?? 1) - 1.0);
      const fastDelta = Math.abs((fastResult.priority ?? 1) - 1.0);
      expect(fastDelta).toBeGreaterThan(slowDelta);
    });

    it("regularization pulls toward base weights", () => {
      const noRegOptimizer = new WeightOptimizer({
        ...defaultConfig,
        regularization: 0,
        minSamples: 2,
      });
      const highRegOptimizer = new WeightOptimizer({
        ...defaultConfig,
        regularization: 0.5,
        minSamples: 2,
      });

      const records = makeRecords(20, i => ({
        quality: i / 20,
        features: [
          {
            priority: i * 5,
            recency: 1,
            salience: 1,
            relevance: 1,
            selected: true,
          },
        ],
      }));

      const noRegResult = noRegOptimizer.optimize(records);
      const highRegResult = highRegOptimizer.optimize(records);

      // High regularization should be closer to base weight
      const noRegDelta = Math.abs((noRegResult.priority ?? 1) - 1.0);
      const highRegDelta = Math.abs((highRegResult.priority ?? 1) - 1.0);
      expect(highRegDelta).toBeLessThanOrEqual(noRegDelta);
    });

    it("handles records without outcomes", () => {
      const optimizer = new WeightOptimizer({
        ...defaultConfig,
        minSamples: 2,
      });
      const records = makeRecords(10, () => ({ quality: 0.5 }));

      // Remove outcomes from some records
      records[0].outcome = undefined;
      records[1].outcome = undefined;

      // Should not throw
      const result = optimizer.optimize(records);
      expect(result.priority).toBeDefined();
    });
  });

  describe("computeCorrelations", () => {
    it("computes positive correlation when dimension tracks quality", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const records = makeRecords(20, i => ({
        quality: i / 20,
        features: [
          {
            priority: i,
            recency: 1,
            salience: 1,
            relevance: 1,
            selected: true,
          },
        ],
      }));

      const correlations = optimizer.computeCorrelations(records);
      expect(correlations.priority).toBeGreaterThan(0.5);
    });

    it("computes negative correlation for inverse relationship", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const records = makeRecords(20, i => ({
        quality: 1 - i / 20,
        features: [
          {
            priority: i,
            recency: 1,
            salience: 1,
            relevance: 1,
            selected: true,
          },
        ],
      }));

      const correlations = optimizer.computeCorrelations(records);
      expect(correlations.priority).toBeLessThan(-0.5);
    });

    it("returns zero correlations for single record", () => {
      const optimizer = new WeightOptimizer(defaultConfig);
      const records = [makeRecord({ quality: 0.5 })];

      const correlations = optimizer.computeCorrelations(records);
      expect(correlations.priority).toBe(0);
      expect(correlations.recency).toBe(0);
    });

    it("returns zero correlations for empty records", () => {
      const optimizer = new WeightOptimizer(defaultConfig);
      const correlations = optimizer.computeCorrelations([]);

      for (const dim of ["priority", "recency", "salience", "relevance"]) {
        expect(correlations[dim]).toBe(0);
      }
    });

    it("handles all-same quality (zero variance)", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const records = makeRecords(10, i => ({
        quality: 0.5,
        features: [
          {
            priority: i,
            recency: i,
            salience: i,
            relevance: i,
            selected: true,
          },
        ],
      }));

      const correlations = optimizer.computeCorrelations(records);
      // With zero quality variance, correlation should be 0
      expect(correlations.priority).toBe(0);
    });
  });

  describe("computeKindInsights", () => {
    it("computes per-kind quality lift", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const records: FeedbackRecord[] = [];

      // Records where including 'code' items leads to high quality
      for (let i = 0; i < 10; i++) {
        records.push({
          id: `r${i}`,
          timestamp: Date.now(),
          packId: `p${i}`,
          segment: "default",
          selectedItemIds: ["item_code"],
          droppedItemIds: [],
          itemFeatures: [
            {
              itemId: "item_code",
              kind: "code",
              priority: 5,
              recency: 1,
              salience: 1,
              relevance: 1,
              tokens: 100,
              selected: true,
            },
          ],
          weightsUsed: BASE_WEIGHTS,
          budget: 1000,
          utilization: 0.8,
          outcome: { quality: 0.9 },
        });
      }

      // Records where 'code' is excluded lead to lower quality
      for (let i = 10; i < 20; i++) {
        records.push({
          id: `r${i}`,
          timestamp: Date.now(),
          packId: `p${i}`,
          segment: "default",
          selectedItemIds: ["item_docs"],
          droppedItemIds: ["item_code"],
          itemFeatures: [
            {
              itemId: "item_code",
              kind: "code",
              priority: 5,
              recency: 1,
              salience: 1,
              relevance: 1,
              tokens: 100,
              selected: false,
            },
            {
              itemId: "item_docs",
              kind: "docs",
              priority: 3,
              recency: 1,
              salience: 1,
              relevance: 1,
              tokens: 50,
              selected: true,
            },
          ],
          weightsUsed: BASE_WEIGHTS,
          budget: 1000,
          utilization: 0.5,
          outcome: { quality: 0.3 },
        });
      }

      const insights = optimizer.computeKindInsights(records);

      const codeInsight = insights.find(i => i.kind === "code");
      expect(codeInsight).toBeDefined();
      expect(codeInsight!.inclusionLift).toBeGreaterThan(0);
      expect(codeInsight!.avgQualityWhenIncluded).toBeGreaterThan(
        codeInsight!.avgQualityWhenExcluded
      );
    });

    it("returns empty array for no records", () => {
      const optimizer = new WeightOptimizer(defaultConfig);
      const insights = optimizer.computeKindInsights([]);
      expect(insights).toEqual([]);
    });

    it("sorts insights by inclusion lift descending", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const records: FeedbackRecord[] = [
        {
          id: "r1",
          timestamp: Date.now(),
          packId: "p1",
          segment: "default",
          selectedItemIds: ["a"],
          droppedItemIds: ["b"],
          itemFeatures: [
            {
              itemId: "a",
              kind: "good",
              priority: 1,
              recency: 1,
              salience: 1,
              relevance: 1,
              tokens: 10,
              selected: true,
            },
            {
              itemId: "b",
              kind: "bad",
              priority: 1,
              recency: 1,
              salience: 1,
              relevance: 1,
              tokens: 10,
              selected: false,
            },
          ],
          weightsUsed: BASE_WEIGHTS,
          budget: 100,
          utilization: 0.5,
          outcome: { quality: 0.9 },
        },
        {
          id: "r2",
          timestamp: Date.now(),
          packId: "p2",
          segment: "default",
          selectedItemIds: ["b"],
          droppedItemIds: ["a"],
          itemFeatures: [
            {
              itemId: "a",
              kind: "good",
              priority: 1,
              recency: 1,
              salience: 1,
              relevance: 1,
              tokens: 10,
              selected: false,
            },
            {
              itemId: "b",
              kind: "bad",
              priority: 1,
              recency: 1,
              salience: 1,
              relevance: 1,
              tokens: 10,
              selected: true,
            },
          ],
          weightsUsed: BASE_WEIGHTS,
          budget: 100,
          utilization: 0.5,
          outcome: { quality: 0.2 },
        },
      ];

      const insights = optimizer.computeKindInsights(records);
      expect(insights[0].kind).toBe("good");
      expect(insights[0].inclusionLift).toBeGreaterThan(0);
    });
  });

  describe("computeConfidence", () => {
    it("returns 0 for empty records", () => {
      const optimizer = new WeightOptimizer(defaultConfig);
      expect(optimizer.computeConfidence([])).toBe(0);
    });

    it("increases with more samples", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const fewRecords = makeRecords(5, i => ({ quality: i / 10 }));
      const manyRecords = makeRecords(100, i => ({ quality: (i % 10) / 10 }));

      const fewConfidence = optimizer.computeConfidence(fewRecords);
      const manyConfidence = optimizer.computeConfidence(manyRecords);

      expect(manyConfidence).toBeGreaterThan(fewConfidence);
    });

    it("returns low confidence for zero-variance quality", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const records = makeRecords(50, () => ({ quality: 0.5 }));
      const confidence = optimizer.computeConfidence(records);

      expect(confidence).toBeLessThan(0.5);
    });

    it("is between 0 and 1", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const records = makeRecords(30, i => ({ quality: i / 30 }));
      const confidence = optimizer.computeConfidence(records);

      expect(confidence).toBeGreaterThanOrEqual(0);
      expect(confidence).toBeLessThanOrEqual(1);
    });

    it("ignores records without outcomes", () => {
      const optimizer = new WeightOptimizer(defaultConfig);

      const records = makeRecords(10, i => ({ quality: i / 10 }));
      records[0].outcome = undefined;
      records[1].outcome = undefined;

      // Should not throw and should produce valid confidence
      const confidence = optimizer.computeConfidence(records);
      expect(confidence).toBeGreaterThanOrEqual(0);
      expect(confidence).toBeLessThanOrEqual(1);
    });
  });

  describe("non-finite quality does not poison results", () => {
    function isFiniteWeights(w: ScoringWeights): boolean {
      return (["priority", "recency", "salience", "relevance"] as const).every(
        d => Number.isFinite(w[d])
      );
    }

    for (const bad of [NaN, Infinity, -Infinity] as const) {
      it(`optimize() stays all-finite with one quality=${bad} record`, () => {
        const optimizer = new WeightOptimizer({
          ...defaultConfig,
          minSamples: 2,
        });

        const records = makeRecords(10, i => ({
          quality: i / 10,
          features: [
            {
              priority: i,
              recency: 1,
              salience: 1,
              relevance: 1,
              selected: true,
            },
          ],
        }));
        // Poison one record's outcome.
        records[3].outcome = { quality: bad };

        const result = optimizer.optimize(records);
        expect(isFiniteWeights(result)).toBe(true);
      });

      it(`getInsights math (correlations/kindInsights) stays finite with quality=${bad}`, () => {
        const optimizer = new WeightOptimizer(defaultConfig);

        const records = makeRecords(10, i => ({
          quality: i / 10,
          features: [
            {
              priority: i,
              recency: 1,
              salience: 1,
              relevance: 1,
              selected: true,
            },
          ],
        }));
        records[5].outcome = { quality: bad };

        const correlations = optimizer.computeCorrelations(records);
        for (const dim of [
          "priority",
          "recency",
          "salience",
          "relevance",
        ] as const) {
          expect(Number.isFinite(correlations[dim])).toBe(true);
        }

        const kindInsights = optimizer.computeKindInsights(records);
        for (const insight of kindInsights) {
          expect(Number.isFinite(insight.avgQualityWhenIncluded)).toBe(true);
          expect(Number.isFinite(insight.avgQualityWhenExcluded)).toBe(true);
          expect(Number.isFinite(insight.inclusionLift)).toBe(true);
        }
      });
    }
  });
});
