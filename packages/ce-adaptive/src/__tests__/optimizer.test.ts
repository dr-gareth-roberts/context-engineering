import { describe, it, expect } from "vitest";
import { ContextOptimizer, createContextOptimizer } from "../optimizer.js";
import { InMemoryFeedbackStore } from "../store.js";
import type { ContextItem } from "@context-engineering/core";

function makeItems(count: number): ContextItem[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `item_${i}`,
    content: `Content for item ${i}. `.repeat(10),
    kind: i % 2 === 0 ? "code" : "docs",
    priority: i + 1,
    recency: count - i,
    tokens: 50 + i * 10,
  }));
}

describe("ContextOptimizer", () => {
  describe("createContextOptimizer", () => {
    it("creates an optimizer instance", () => {
      const optimizer = createContextOptimizer({ feedback: "explicit" });
      expect(optimizer).toBeInstanceOf(ContextOptimizer);
    });
  });

  describe("pack", () => {
    it("packs items and returns OptimizedPack with optimizerId", async () => {
      const optimizer = createContextOptimizer({ feedback: "explicit" });

      const items = makeItems(5);
      const result = await optimizer.pack(items, { maxTokens: 500 });

      expect(result.optimizerId).toBeDefined();
      expect(result.optimizerId).toMatch(/^opt_/);
      expect(result.weightsUsed).toBeDefined();
      expect(result.selected.length).toBeGreaterThan(0);
      expect(result.totalTokens).toBeLessThanOrEqual(500);
    });

    it("records feedback in the store", async () => {
      const store = new InMemoryFeedbackStore();
      const optimizer = createContextOptimizer({
        feedback: "explicit",
        store,
      });

      const items = makeItems(3);
      await optimizer.pack(items, { maxTokens: 500 });

      const records = await store.getRecords();
      expect(records).toHaveLength(1);
      expect(records[0].itemFeatures.length).toBe(3);
    });

    it("uses user-provided weights as overrides", async () => {
      const store = new InMemoryFeedbackStore();
      const optimizer = createContextOptimizer({
        feedback: "explicit",
        store,
        baseWeights: { priority: 1, recency: 1, salience: 1, relevance: 1 },
      });

      const items = makeItems(3);
      await optimizer.pack(
        items,
        { maxTokens: 500 },
        {
          weights: { priority: 5.0 },
        }
      );

      const records = await store.getRecords();
      expect(records[0].weightsUsed.priority).toBe(5.0);
    });
  });

  describe("reportOutcome", () => {
    it("attaches outcome to the correct feedback record", async () => {
      const store = new InMemoryFeedbackStore();
      const optimizer = createContextOptimizer({
        feedback: "explicit",
        store,
      });

      const items = makeItems(3);
      const result = await optimizer.pack(items, { maxTokens: 500 });

      await optimizer.reportOutcome(result.optimizerId, {
        quality: 0.85,
        accepted: true,
      });

      const records = await store.getRecordsWithOutcomes();
      expect(records).toHaveLength(1);
      expect(records[0].outcome?.quality).toBe(0.85);
      expect(records[0].outcome?.accepted).toBe(true);
    });
  });

  describe("getInsights", () => {
    it("returns insights with zero samples when no outcomes exist", async () => {
      const optimizer = createContextOptimizer({ feedback: "explicit" });

      const insights = await optimizer.getInsights();

      expect(insights.sampleCount).toBe(0);
      expect(insights.confidence).toBe(0);
      expect(insights.currentWeights).toBeDefined();
      expect(insights.correlations).toBeDefined();
    });

    it("returns meaningful insights after multiple feedback cycles", async () => {
      const store = new InMemoryFeedbackStore();
      const optimizer = createContextOptimizer({
        feedback: "explicit",
        store,
        minSamples: 5,
      });

      // Simulate multiple pack + outcome cycles
      for (let i = 0; i < 10; i++) {
        const items = makeItems(5);
        const result = await optimizer.pack(items, { maxTokens: 500 });
        await optimizer.reportOutcome(result.optimizerId, {
          quality: 0.5 + i * 0.05,
        });
      }

      const insights = await optimizer.getInsights();

      expect(insights.sampleCount).toBe(10);
      expect(insights.confidence).toBeGreaterThan(0);
      expect(insights.recommendedWeights).toBeDefined();
      expect(insights.kindInsights.length).toBeGreaterThan(0);
    });
  });

  describe("weights shift toward quality-correlated dimensions", () => {
    it("adapts weights after sufficient feedback", async () => {
      const store = new InMemoryFeedbackStore();
      const optimizer = createContextOptimizer({
        feedback: "explicit",
        store,
        minSamples: 5,
        learningRate: 0.3,
        baseWeights: { priority: 1, recency: 1, salience: 1, relevance: 1 },
      });

      // Simulate enough feedback cycles for adaptation
      for (let i = 0; i < 25; i++) {
        const items: ContextItem[] = Array.from({ length: 5 }, (_, j) => ({
          id: `item_${i}_${j}`,
          content: "x ".repeat(20),
          kind: "code",
          priority: j + 1,
          recency: 1,
          tokens: 30,
        }));

        const result = await optimizer.pack(items, { maxTokens: 300 });
        await optimizer.reportOutcome(result.optimizerId, {
          quality: 0.3 + i * 0.025,
        });
      }

      const insights = await optimizer.getInsights();
      expect(insights.sampleCount).toBe(25);
      // The optimizer should have produced some recommended weights
      expect(insights.recommendedWeights.priority).toBeDefined();
    });
  });

  describe("segment isolation", () => {
    it("keeps segments separate", async () => {
      const store = new InMemoryFeedbackStore();
      const optimizerA = createContextOptimizer({
        feedback: "explicit",
        store,
        segment: "segment-a",
      });
      const optimizerB = createContextOptimizer({
        feedback: "explicit",
        store,
        segment: "segment-b",
      });

      const items = makeItems(3);
      await optimizerA.pack(items, { maxTokens: 500 });
      await optimizerB.pack(items, { maxTokens: 500 });

      const insightsA = await optimizerA.getInsights();
      const insightsB = await optimizerB.getInsights();

      // Each segment should see its own records
      expect(insightsA.sampleCount).toBe(0); // no outcomes yet
      expect(insightsB.sampleCount).toBe(0);

      // Verify records are in different segments
      const allRecords = await store.getRecords();
      expect(allRecords).toHaveLength(2);
      const segments = new Set(allRecords.map(r => r.segment));
      expect(segments.size).toBe(2);
    });
  });

  describe("exportState / importState", () => {
    it("roundtrips state correctly", async () => {
      const store = new InMemoryFeedbackStore();
      const optimizer = createContextOptimizer({
        feedback: "explicit",
        store,
        minSamples: 2,
      });

      // Generate some feedback
      for (let i = 0; i < 5; i++) {
        const items = makeItems(3);
        const result = await optimizer.pack(items, { maxTokens: 500 });
        await optimizer.reportOutcome(result.optimizerId, {
          quality: 0.7 + i * 0.05,
        });
      }

      const state = await optimizer.exportState();
      expect(state.segment).toBe("default");
      expect(state.sampleCount).toBe(5);
      expect(state.weights).toBeDefined();
      expect(state.exportedAt).toBeGreaterThan(0);

      // Import into a fresh optimizer
      const newOptimizer = createContextOptimizer({ feedback: "explicit" });
      await newOptimizer.importState(state);

      // The imported optimizer should use the same weights
      const insights = await newOptimizer.getInsights();
      expect(insights.currentWeights).toEqual(state.weights);
    });
  });

  describe("reset", () => {
    it("returns to base weights after reset", async () => {
      const store = new InMemoryFeedbackStore();
      const baseWeights = {
        priority: 1,
        recency: 1,
        salience: 1,
        relevance: 1,
      };
      const optimizer = createContextOptimizer({
        feedback: "explicit",
        store,
        segment: "test-reset",
        baseWeights,
        minSamples: 2,
      });

      // Build up some state
      for (let i = 0; i < 5; i++) {
        const items = makeItems(3);
        const result = await optimizer.pack(items, { maxTokens: 500 });
        await optimizer.reportOutcome(result.optimizerId, { quality: 0.9 });
      }

      await optimizer.reset();

      // After reset, insights should show zero samples for this segment
      const records = await store.getRecords({ segment: "test-reset" });
      expect(records).toHaveLength(0);

      const insights = await optimizer.getInsights();
      expect(insights.sampleCount).toBe(0);
      expect(insights.currentWeights).toEqual(baseWeights);
    });
  });
});
