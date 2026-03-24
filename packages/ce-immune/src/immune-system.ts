import type { ContextItem, Budget } from "@context-engineering/core";
import type {
  Antibody,
  FailureRecord,
  ImmuneSystem,
  ImmuneSystemConfig,
  ImmuneSystemState,
  ScreeningAlert,
  ScreeningResult,
} from "./types.js";
import { extractFingerprint } from "./fingerprint.js";
import { createAntibody, matchAntibody } from "./antibodies.js";

const DEFAULT_MATCH_THRESHOLD = 0.7;
const DEFAULT_MAX_ANTIBODIES = 100;

/**
 * Create a Context Immune System that learns from past failures
 * and screens future context packs against known toxic patterns.
 */
export function createImmuneSystem(config?: ImmuneSystemConfig): ImmuneSystem {
  const matchThreshold = config?.matchThreshold ?? DEFAULT_MATCH_THRESHOLD;
  const maxAntibodies = config?.maxAntibodies ?? DEFAULT_MAX_ANTIBODIES;
  const onAlert = config?.onAlert;

  let antibodies: Antibody[] = [];
  let failureCount = 0;

  function pruneIfNeeded(): void {
    if (antibodies.length > maxAntibodies) {
      // Sort by createdAt ascending, keep the newest
      antibodies.sort((a, b) => a.createdAt - b.createdAt);
      antibodies = antibodies.slice(antibodies.length - maxAntibodies);
    }
  }

  function recordFailure(record: FailureRecord): Antibody {
    failureCount++;
    const antibody = createAntibody(record, matchThreshold);
    antibodies.push(antibody);
    pruneIfNeeded();
    return antibody;
  }

  function screen(items: ContextItem[], budget?: Budget): ScreeningResult {
    const fingerprint = extractFingerprint(items, budget);

    const warnings: ScreeningAlert[] = [];
    const blocked: ScreeningAlert[] = [];
    const antibodiesFired: Antibody[] = [];

    for (const antibody of antibodies) {
      const { matches, similarity } = matchAntibody(antibody, fingerprint);
      if (matches) {
        const alert: ScreeningAlert = {
          antibodyId: antibody.id,
          similarity,
          symptom: antibody.symptom,
          diagnosis: antibody.diagnosis,
          severity: antibody.severity,
        };

        antibodiesFired.push(antibody);

        if (antibody.severity === "block") {
          blocked.push(alert);
        } else {
          warnings.push(alert);
        }
      }
    }

    const result: ScreeningResult = {
      safe: blocked.length === 0,
      warnings,
      blocked,
      antibodiesFired,
    };

    if ((warnings.length > 0 || blocked.length > 0) && onAlert) {
      onAlert(result);
    }

    return result;
  }

  function getAntibodies(): Antibody[] {
    return [...antibodies];
  }

  function removeAntibody(id: string): boolean {
    const index = antibodies.findIndex(ab => ab.id === id);
    if (index === -1) return false;
    antibodies.splice(index, 1);
    return true;
  }

  function reset(): void {
    antibodies = [];
    failureCount = 0;
  }

  function exportState(): ImmuneSystemState {
    return {
      antibodies: [...antibodies],
      failureCount,
    };
  }

  function importState(state: ImmuneSystemState): void {
    antibodies = [...state.antibodies];
    failureCount = state.failureCount;
    pruneIfNeeded();
  }

  return {
    recordFailure,
    screen,
    getAntibodies,
    removeAntibody,
    reset,
    exportState,
    importState,
  };
}
