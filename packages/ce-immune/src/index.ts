export type {
  Fingerprint,
  Antibody,
  FailureRecord,
  ScreeningResult,
  ScreeningAlert,
  ImmuneSystemConfig,
  ImmuneSystemState,
  ImmuneSystem,
} from "./types.js";

export {
  computeStats,
  extractFingerprint,
  compareFingerprints,
} from "./fingerprint.js";

export { createAntibody, matchAntibody, resetIdCounter } from "./antibodies.js";

export { createImmuneSystem } from "./immune-system.js";
