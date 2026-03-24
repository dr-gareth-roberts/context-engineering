import type {
  ContextItem,
  Budget,
  PackOptions,
} from "@context-engineering/core";

export type AttackType =
  | "contradiction"
  | "noise-flood"
  | "subtle-error"
  | "authority-spoof"
  | "temporal-poison"
  | "relevance-dilution";

export interface AttackConfig {
  type: AttackType;
  /** Intensity from 0 to 1. Higher = more aggressive attack. Default: 0.5 */
  intensity?: number;
}

export interface AdversarialConfig {
  attacks: (AttackType | AttackConfig)[];
  /** Number of probe rounds per attack. Default: 3 */
  probeRounds?: number;
}

export interface QualityCallback {
  (packed: ContextItem[]): Promise<number>;
}

export interface AttackResult {
  attack: AttackType;
  baselineQuality: number;
  attackedQuality: number;
  /** baseline - attacked (positive means quality dropped) */
  qualityDrop: number;
  severity: "resilient" | "vulnerable" | "critical";
  injectedCount: number;
  description: string;
}

export interface ProbeReport {
  overall: "resilient" | "vulnerable" | "critical";
  baselineQuality: number;
  worstAttack: AttackResult | null;
  attacks: AttackResult[];
  totalProbes: number;
  durationMs: number;
}

export interface AdversarialTester {
  probe(
    items: ContextItem[],
    budget: Budget,
    evaluator: QualityCallback,
    options?: PackOptions
  ): Promise<ProbeReport>;
}

export interface AttackFunction {
  (items: ContextItem[], intensity: number, seed: number): ContextItem[];
}
