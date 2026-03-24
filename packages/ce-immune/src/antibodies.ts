import type { Antibody, FailureRecord } from "./types.js";
import type { Fingerprint } from "./types.js";
import { extractFingerprint, compareFingerprints } from "./fingerprint.js";

let antibodyCounter = 0;

/**
 * Generate a deterministic antibody ID based on an internal counter.
 */
function generateAntibodyId(): string {
  antibodyCounter++;
  return `ab-${antibodyCounter}`;
}

/**
 * Reset the ID counter. Useful for testing.
 */
export function resetIdCounter(): void {
  antibodyCounter = 0;
}

/**
 * Create an antibody from a failure record.
 * Extracts the fingerprint from the failed context configuration
 * and wraps it with the failure metadata.
 */
export function createAntibody(
  record: FailureRecord,
  threshold?: number
): Antibody {
  const pattern = extractFingerprint(record.items, record.budget);

  return {
    id: generateAntibodyId(),
    pattern,
    symptom: record.symptom,
    diagnosis: record.diagnosis ?? "Unknown cause",
    severity: record.severity ?? "warning",
    createdAt: Date.now(),
    matchThreshold: threshold ?? 0.7,
  };
}

/**
 * Check whether an antibody matches a given fingerprint.
 * Returns the match result with the computed similarity score.
 */
export function matchAntibody(
  antibody: Antibody,
  fingerprint: Fingerprint
): { matches: boolean; similarity: number } {
  const similarity = compareFingerprints(antibody.pattern, fingerprint);
  return {
    matches: similarity >= antibody.matchThreshold,
    similarity,
  };
}
