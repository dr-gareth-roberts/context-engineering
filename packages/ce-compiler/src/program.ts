import type { Slot, Constraint, ContextProgram } from "./types.js";

/**
 * Fluent builder for declaring context programs.
 *
 * A ContextProgram declares what the context should contain (slots, constraints,
 * priorities) without specifying how to arrange it. The compiler then optimizes
 * the layout for a target model.
 *
 * @example
 * ```ts
 * const program = contextProgram()
 *   .declare("system", { kind: "system", required: true, position: "first" })
 *   .declare("code", { kind: "code", strategy: "relevance", deduplicate: true })
 *   .declare("history", { kind: "history", position: "last", fillRemaining: true })
 *   .constraint("coverage")
 *   .constraint("max-redundancy", { threshold: 0.3 })
 *   .build();
 * ```
 */
export interface ContextProgramBuilder {
  declare(name: string, slot: Omit<Slot, "name">): ContextProgramBuilder;
  constraint(
    type: Constraint["type"],
    options?: Omit<Constraint, "type">
  ): ContextProgramBuilder;
  build(): ContextProgram;
}

class ContextProgramBuilderImpl implements ContextProgramBuilder {
  private readonly slots: Slot[] = [];
  private readonly constraints: Constraint[] = [];

  declare(name: string, slot: Omit<Slot, "name">): ContextProgramBuilder {
    this.slots.push({ name, ...slot });
    return this;
  }

  constraint(
    type: Constraint["type"],
    options?: Omit<Constraint, "type">
  ): ContextProgramBuilder {
    this.constraints.push({ type, ...options });
    return this;
  }

  build(): ContextProgram {
    return {
      slots: [...this.slots],
      constraints: [...this.constraints],
    };
  }
}

export function contextProgram(): ContextProgramBuilder {
  return new ContextProgramBuilderImpl();
}
