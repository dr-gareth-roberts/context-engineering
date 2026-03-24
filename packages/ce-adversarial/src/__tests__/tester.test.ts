import { describe, it, expect } from "vitest";
import type { ContextItem, Budget } from "@context-engineering/core";
import { createAdversarialTester } from "../tester.js";
import type { AttackType, QualityCallback } from "../types.js";

function makeItems(count: number): ContextItem[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `item-${i}`,
    content: `Context item number ${i} with important information about the project.`,
    priority: 5 + i,
    recency: 5,
    tokens: 15,
  }));
}

const defaultBudget: Budget = { maxTokens: 5000 };

/**
 * Mock evaluator that scores based on the ratio of non-adversarial items.
 * Returns high quality when no adversarial items, lower when diluted.
 */
function createMockEvaluator(): QualityCallback {
  return async (packed: ContextItem[]): Promise<number> => {
    if (packed.length === 0) return 0;
    const legitimate = packed.filter(i => !i.id.startsWith("adversarial-"));
    return legitimate.length / packed.length;
  };
}

/**
 * Evaluator that always returns the same score (resilient pipeline).
 */
function createResilientEvaluator(): QualityCallback {
  return async (_packed: ContextItem[]): Promise<number> => 0.9;
}

/**
 * Evaluator that returns 0 for any adversarial content (critical vulnerability).
 */
function createVulnerableEvaluator(): QualityCallback {
  return async (packed: ContextItem[]): Promise<number> => {
    const hasAdversarial = packed.some(i => i.id.startsWith("adversarial-"));
    return hasAdversarial ? 0.1 : 0.9;
  };
}

describe("createAdversarialTester", () => {
  it("runs a full probe cycle end-to-end", async () => {
    const tester = createAdversarialTester({
      attacks: ["contradiction", "noise-flood"],
      probeRounds: 1,
    });

    const items = makeItems(5);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    expect(report).toHaveProperty("overall");
    expect(report).toHaveProperty("baselineQuality");
    expect(report).toHaveProperty("worstAttack");
    expect(report).toHaveProperty("attacks");
    expect(report).toHaveProperty("totalProbes");
    expect(report).toHaveProperty("durationMs");
    expect(report.attacks).toHaveLength(2);
  });

  it("measures baseline quality correctly", async () => {
    const tester = createAdversarialTester({
      attacks: ["contradiction"],
      probeRounds: 1,
    });

    const items = makeItems(3);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    // Baseline with only legitimate items should be 1.0
    expect(report.baselineQuality).toBe(1.0);
  });

  it("detects quality drop from attacks", async () => {
    const tester = createAdversarialTester({
      attacks: ["noise-flood"],
      probeRounds: 1,
    });

    const items = makeItems(3);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    const noiseResult = report.attacks[0];
    expect(noiseResult.qualityDrop).toBeGreaterThan(0);
    expect(noiseResult.injectedCount).toBeGreaterThan(0);
  });

  describe("severity classification", () => {
    it("classifies resilient pipelines correctly", async () => {
      const tester = createAdversarialTester({
        attacks: ["contradiction"],
        probeRounds: 1,
      });

      const items = makeItems(3);
      const report = await tester.probe(
        items,
        defaultBudget,
        createResilientEvaluator()
      );

      expect(report.overall).toBe("resilient");
      expect(report.attacks[0].severity).toBe("resilient");
    });

    it("classifies vulnerable pipelines correctly", async () => {
      // Evaluator returns 0.9 baseline, ~0.7 attacked = ~0.2 drop = vulnerable
      const evaluator: QualityCallback = async packed => {
        const hasAdversarial = packed.some(i =>
          i.id.startsWith("adversarial-")
        );
        return hasAdversarial ? 0.7 : 0.9;
      };

      const tester = createAdversarialTester({
        attacks: ["contradiction"],
        probeRounds: 1,
      });

      const items = makeItems(3);
      const report = await tester.probe(items, defaultBudget, evaluator);

      expect(report.attacks[0].severity).toBe("vulnerable");
    });

    it("classifies critical pipelines correctly", async () => {
      const tester = createAdversarialTester({
        attacks: ["authority-spoof"],
        probeRounds: 1,
      });

      const items = makeItems(3);
      const report = await tester.probe(
        items,
        defaultBudget,
        createVulnerableEvaluator()
      );

      expect(report.attacks[0].severity).toBe("critical");
    });
  });

  it("identifies the worst attack", async () => {
    const tester = createAdversarialTester({
      attacks: ["contradiction", "noise-flood", "authority-spoof"],
      probeRounds: 1,
    });

    const items = makeItems(5);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    expect(report.worstAttack).not.toBeNull();
    const maxDrop = Math.max(...report.attacks.map(a => a.qualityDrop));
    expect(report.worstAttack!.qualityDrop).toBe(maxDrop);
  });

  it("reports correct total probe count", async () => {
    const probeRounds = 2;
    const attacks: AttackType[] = [
      "contradiction",
      "noise-flood",
      "subtle-error",
    ];
    const tester = createAdversarialTester({ attacks, probeRounds });

    const items = makeItems(3);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    // baseline probes + per-attack probes
    const expected = probeRounds + attacks.length * probeRounds;
    expect(report.totalProbes).toBe(expected);
  });

  it("reports non-negative durationMs", async () => {
    const tester = createAdversarialTester({
      attacks: ["contradiction"],
      probeRounds: 1,
    });

    const items = makeItems(2);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    expect(report.durationMs).toBeGreaterThanOrEqual(0);
  });

  it("handles all six attack types in a single probe", async () => {
    const allAttacks: AttackType[] = [
      "contradiction",
      "noise-flood",
      "subtle-error",
      "authority-spoof",
      "temporal-poison",
      "relevance-dilution",
    ];
    const tester = createAdversarialTester({
      attacks: allAttacks,
      probeRounds: 1,
    });

    const items = makeItems(5);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    expect(report.attacks).toHaveLength(6);
    for (const result of report.attacks) {
      expect(result.description.length).toBeGreaterThan(0);
    }
  });

  it("handles empty items array", async () => {
    const tester = createAdversarialTester({
      attacks: ["contradiction"],
      probeRounds: 1,
    });

    const report = await tester.probe([], defaultBudget, createMockEvaluator());

    expect(report.baselineQuality).toBe(0);
    expect(report.attacks).toHaveLength(1);
  });

  it("handles empty attacks config", async () => {
    const tester = createAdversarialTester({
      attacks: [],
      probeRounds: 1,
    });

    const items = makeItems(3);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    expect(report.attacks).toHaveLength(0);
    expect(report.overall).toBe("resilient");
    expect(report.worstAttack).toBeNull();
  });

  it("accepts AttackConfig objects with custom intensity", async () => {
    const tester = createAdversarialTester({
      attacks: [{ type: "noise-flood", intensity: 0.9 }],
      probeRounds: 1,
    });

    const items = makeItems(3);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    expect(report.attacks).toHaveLength(1);
    expect(report.attacks[0].attack).toBe("noise-flood");
  });

  it("correctly defaults intensity to 0.5", async () => {
    const tester = createAdversarialTester({
      attacks: ["contradiction"],
      probeRounds: 1,
    });

    const items = makeItems(5);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    // Should work correctly with default intensity
    expect(report.attacks[0].injectedCount).toBeGreaterThan(0);
  });

  it("overall severity reflects worst individual attack", async () => {
    // One attack resilient, one critical
    const evaluator: QualityCallback = async packed => {
      const hasAuthority = packed.some(i =>
        i.id.startsWith("adversarial-authority-")
      );
      const hasNoise = packed.some(i => i.id.startsWith("adversarial-noise-"));
      if (hasAuthority) return 0.1; // critical drop
      if (hasNoise) return 0.85; // resilient drop
      return 0.9;
    };

    const tester = createAdversarialTester({
      attacks: ["noise-flood", "authority-spoof"],
      probeRounds: 1,
    });

    const items = makeItems(5);
    const report = await tester.probe(items, defaultBudget, evaluator);

    expect(report.overall).toBe("critical");
  });

  it("each attack result includes a description", async () => {
    const tester = createAdversarialTester({
      attacks: ["contradiction", "noise-flood"],
      probeRounds: 1,
    });

    const items = makeItems(3);
    const report = await tester.probe(
      items,
      defaultBudget,
      createMockEvaluator()
    );

    for (const result of report.attacks) {
      expect(result.description).toBeTruthy();
      expect(typeof result.description).toBe("string");
    }
  });
});
