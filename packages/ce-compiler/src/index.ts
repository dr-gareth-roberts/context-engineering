export type {
  Slot,
  Constraint,
  CompileTarget,
  CompileOptions,
  CompileDiagnostic,
  OptimizationPass,
  CompileResult,
  ContextProgram,
  ContextCompiler,
} from "./types.js";

export { contextProgram } from "./program.js";
export type { ContextProgramBuilder } from "./program.js";

export { validateConstraints } from "./constraints.js";

export { optimizeForTarget } from "./optimizer.js";

export { createContextCompiler } from "./compiler.js";
