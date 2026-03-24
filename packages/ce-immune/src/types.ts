import type { ContextItem, Budget } from "@context-engineering/core";

export interface Fingerprint {
  kindsPresent: string[];
  kindRatios: Record<string, number>;
  priorityStats: { min: number; max: number; mean: number; std: number };
  recencyStats: { min: number; max: number; mean: number; std: number };
  tokenUtilization: number;
  itemCount: number;
  stalenessRatio: number;
  redundancyEstimate: number;
}

export interface Antibody {
  id: string;
  pattern: Fingerprint;
  symptom: string;
  diagnosis: string;
  severity: "warning" | "block";
  createdAt: number;
  matchThreshold: number;
}

export interface FailureRecord {
  items: ContextItem[];
  budget: Budget;
  symptom: string;
  diagnosis?: string;
  severity?: "warning" | "block";
  metadata?: Record<string, unknown>;
}

export interface ScreeningResult {
  safe: boolean;
  warnings: ScreeningAlert[];
  blocked: ScreeningAlert[];
  antibodiesFired: Antibody[];
}

export interface ScreeningAlert {
  antibodyId: string;
  similarity: number;
  symptom: string;
  diagnosis: string;
  severity: "warning" | "block";
}

export interface ImmuneSystemConfig {
  /** Default match threshold for antibodies (0-1). Default: 0.7 */
  matchThreshold?: number;
  /** Max antibodies to retain. Oldest pruned when exceeded. Default: 100 */
  maxAntibodies?: number;
  /** Called when a screening finds issues */
  onAlert?: (result: ScreeningResult) => void;
}

export interface ImmuneSystemState {
  antibodies: Antibody[];
  failureCount: number;
}

export interface ImmuneSystem {
  /** Record a context failure. Creates an antibody from the failure pattern. */
  recordFailure(record: FailureRecord): Antibody;

  /** Screen a set of items against known failure patterns. */
  screen(items: ContextItem[], budget?: Budget): ScreeningResult;

  /** Get all antibodies */
  getAntibodies(): Antibody[];

  /** Remove an antibody by ID */
  removeAntibody(id: string): boolean;

  /** Reset all antibodies */
  reset(): void;

  /** Export state for persistence */
  exportState(): ImmuneSystemState;

  /** Import previously exported state */
  importState(state: ImmuneSystemState): void;
}
