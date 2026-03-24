import type {
  ContextItem,
  Budget,
  PackOptions,
} from "@context-engineering/core";
import { pack } from "@context-engineering/core";
import type {
  AdversarialConfig,
  AdversarialTester,
  AttackConfig,
  AttackResult,
  AttackType,
  ProbeReport,
  QualityCallback,
} from "./types.js";
import { applyAttack, countInjected, describeAttack } from "./attacks.js";

/** Default number of probe rounds per attack */
const DEFAULT_PROBE_ROUNDS = 3;
/** Default seed for deterministic RNG */
const DEFAULT_SEED = 42;

function normalizeAttack(attack: AttackType | AttackConfig): AttackConfig {
  if (typeof attack === "string") {
    return { type: attack, intensity: 0.5 };
  }
  return { ...attack, intensity: attack.intensity ?? 0.5 };
}

function classifySeverity(
  qualityDrop: number
): "resilient" | "vulnerable" | "critical" {
  if (qualityDrop < 0.1) return "resilient";
  if (qualityDrop <= 0.3) return "vulnerable";
  return "critical";
}

function worstSeverity(
  severities: Array<"resilient" | "vulnerable" | "critical">
): "resilient" | "vulnerable" | "critical" {
  if (severities.includes("critical")) return "critical";
  if (severities.includes("vulnerable")) return "vulnerable";
  return "resilient";
}

async function measureQuality(
  items: ContextItem[],
  budget: Budget,
  evaluator: QualityCallback,
  options: PackOptions | undefined,
  rounds: number
): Promise<number> {
  let total = 0;
  for (let i = 0; i < rounds; i++) {
    const packed = pack(items, budget, options);
    const score = await evaluator(packed.selected);
    total += score;
  }
  return total / rounds;
}

/**
 * Create an adversarial tester that probes context pipelines for weaknesses.
 *
 * The tester applies each configured attack, packs the result, and measures
 * quality degradation using the provided evaluator callback.
 */
export function createAdversarialTester(
  config: AdversarialConfig
): AdversarialTester {
  const probeRounds = config.probeRounds ?? DEFAULT_PROBE_ROUNDS;
  const attacks = config.attacks.map(normalizeAttack);

  return {
    async probe(
      items: ContextItem[],
      budget: Budget,
      evaluator: QualityCallback,
      options?: PackOptions
    ): Promise<ProbeReport> {
      const startTime = Date.now();

      // Measure baseline quality
      const baselineQuality = await measureQuality(
        items,
        budget,
        evaluator,
        options,
        probeRounds
      );

      const attackResults: AttackResult[] = [];
      let totalProbes = probeRounds; // baseline probes

      for (const attackConfig of attacks) {
        const { type, intensity } = attackConfig;
        const seed = DEFAULT_SEED;

        // Apply the attack
        const attackedItems = applyAttack(type, items, intensity ?? 0.5, seed);
        const injected = countInjected(items, attackedItems);

        // Measure attacked quality
        const attackedQuality = await measureQuality(
          attackedItems,
          budget,
          evaluator,
          options,
          probeRounds
        );
        totalProbes += probeRounds;

        const qualityDrop = baselineQuality - attackedQuality;
        const severity = classifySeverity(qualityDrop);

        attackResults.push({
          attack: type,
          baselineQuality,
          attackedQuality,
          qualityDrop,
          severity,
          injectedCount: injected,
          description: describeAttack(type),
        });
      }

      const worstAttack =
        attackResults.length > 0
          ? attackResults.reduce((worst, current) =>
              current.qualityDrop > worst.qualityDrop ? current : worst
            )
          : null;

      const overall = worstSeverity(attackResults.map(r => r.severity));

      return {
        overall: attackResults.length === 0 ? "resilient" : overall,
        baselineQuality,
        worstAttack,
        attacks: attackResults,
        totalProbes,
        durationMs: Date.now() - startTime,
      };
    },
  };
}
