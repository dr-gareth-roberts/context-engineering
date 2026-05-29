import type {
  ContextItem,
  Budget,
  PackOptions,
} from "@context-engineering/core";
import type { ContextQuality } from "@context-engineering/core";

/** A slot declares a category of content the context needs. */
export interface Slot {
  name: string;
  kind: string;
  required?: boolean;
  position?: "first" | "last" | "any";
  maxTokens?: number;
  minTokens?: number;
  /** Fill remaining budget after required slots are satisfied */
  fillRemaining?: boolean;
  /** Strategy for selecting items within this slot */
  strategy?: "priority" | "recency" | "relevance";
  /** Deduplicate items within this slot */
  deduplicate?: boolean;
  /**
   * Minimum recency score (0-10 scale) an item must have to be kept in this slot.
   * Items whose `recency` is below this value are pruned by the staleness-pruning pass.
   * Matched by slot `kind`. Note: this is a recency floor, NOT a max age in seconds.
   */
  maxStaleness?: number;
}

/** A constraint on the compiled context */
export interface Constraint {
  type:
    | "no-contradiction"
    | "freshness"
    | "coverage"
    | "budget-utilization"
    | "max-redundancy";
  /** Which slots this constraint applies to */
  slots?: string[];
  /** Threshold value (meaning depends on constraint type) */
  threshold?: number;
}

/** Target model for optimization */
export type CompileTarget = "claude" | "gpt4" | "gemini" | "generic";

export interface CompileOptions {
  target: CompileTarget;
  items: ContextItem[];
  budget: Budget;
  packOptions?: PackOptions;
}

export interface CompileDiagnostic {
  level: "info" | "warning" | "error";
  slot?: string;
  constraint?: string;
  message: string;
}

export interface OptimizationPass {
  name: string;
  description: string;
  itemsReordered: number;
  tokensAffected: number;
}

export interface CompileResult {
  /** The optimized context items, ready to send */
  items: ContextItem[];
  /** Items that were dropped */
  dropped: ContextItem[];
  /** Total tokens used */
  totalTokens: number;
  /** Diagnostics (unmet constraints, warnings) */
  diagnostics: CompileDiagnostic[];
  /** Which optimization passes were applied */
  optimizations: OptimizationPass[];
  /** Target model */
  target: CompileTarget;
  /** Per-slot breakdown */
  slots: Record<
    string,
    { itemCount: number; tokensUsed: number; satisfied: boolean }
  >;
  /** Quality metrics of the final context */
  quality: ContextQuality;
}

export interface ContextProgram {
  slots: Slot[];
  constraints: Constraint[];
}

export interface ContextCompiler {
  compile(program: ContextProgram, options: CompileOptions): CompileResult;
}

export type { ContextItem, Budget, PackOptions, ContextQuality };
