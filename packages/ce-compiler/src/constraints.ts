import type { ContextItem, Budget } from "@context-engineering/core";
import { estimateTokens } from "@context-engineering/core";
import type { Slot, Constraint, CompileDiagnostic } from "./types.js";

const NEGATION_WORDS = new Set([
  "not",
  "never",
  "don't",
  "dont",
  "avoid",
  "shouldn't",
  "shouldnt",
  "won't",
  "wont",
  "cannot",
  "can't",
  "cant",
  "no",
]);

function getWords(text: string): string[] {
  return text
    .toLowerCase()
    .split(/\s+/)
    .filter(w => w.length > 0);
}

function wordSet(words: string[]): Set<string> {
  return new Set(words);
}

function hasNegation(words: string[]): boolean {
  return words.some(w => NEGATION_WORDS.has(w));
}

function wordOverlap(a: Set<string>, b: Set<string>): number {
  let intersection = 0;
  for (const word of a) {
    if (b.has(word)) intersection++;
  }
  const union = a.size + b.size - intersection;
  return union > 0 ? intersection / union : 0;
}

function itemsForSlots(
  items: ContextItem[],
  slots: Slot[],
  constraintSlots?: string[]
): ContextItem[] {
  const slotKinds = new Set<string>();
  const targetSlots = constraintSlots
    ? slots.filter(s => constraintSlots.includes(s.name))
    : slots;

  for (const slot of targetSlots) {
    slotKinds.add(slot.kind);
  }

  return items.filter(item => item.kind && slotKinds.has(item.kind));
}

function validateNoContradiction(
  items: ContextItem[],
  constraint: Constraint,
  slots: Slot[]
): CompileDiagnostic[] {
  const diagnostics: CompileDiagnostic[] = [];
  const relevant = itemsForSlots(items, slots, constraint.slots);

  for (let i = 0; i < relevant.length; i++) {
    for (let j = i + 1; j < relevant.length; j++) {
      const wordsA = getWords(relevant[i].content);
      const wordsB = getWords(relevant[j].content);
      const setA = wordSet(wordsA);
      const setB = wordSet(wordsB);
      const overlap = wordOverlap(setA, setB);

      if (overlap > 0.6) {
        const negA = hasNegation(wordsA);
        const negB = hasNegation(wordsB);

        if (negA !== negB) {
          diagnostics.push({
            level: "warning",
            constraint: "no-contradiction",
            message: `Potential contradiction between items "${relevant[i].id}" and "${relevant[j].id}" (overlap: ${Math.round(overlap * 100)}%, negation mismatch)`,
          });
        }
      }
    }
  }

  return diagnostics;
}

function validateFreshness(
  items: ContextItem[],
  constraint: Constraint,
  slots: Slot[]
): CompileDiagnostic[] {
  const diagnostics: CompileDiagnostic[] = [];
  const threshold = constraint.threshold ?? 5;
  const relevant = itemsForSlots(items, slots, constraint.slots);

  for (const item of relevant) {
    const recency = item.recency ?? 0;
    if (recency < threshold) {
      diagnostics.push({
        level: "warning",
        constraint: "freshness",
        message: `Item "${item.id}" has low recency (${recency}) below threshold (${threshold})`,
      });
    }
  }

  return diagnostics;
}

function validateCoverage(
  items: ContextItem[],
  _constraint: Constraint,
  slots: Slot[]
): CompileDiagnostic[] {
  const diagnostics: CompileDiagnostic[] = [];
  const itemKinds = new Set(items.map(item => item.kind).filter(Boolean));

  for (const slot of slots) {
    if (slot.required && !itemKinds.has(slot.kind)) {
      diagnostics.push({
        level: "error",
        slot: slot.name,
        constraint: "coverage",
        message: `Required slot "${slot.name}" (kind: "${slot.kind}") has no matching items`,
      });
    }
  }

  return diagnostics;
}

function validateBudgetUtilization(
  items: ContextItem[],
  constraint: Constraint,
  _slots: Slot[],
  budget: Budget
): CompileDiagnostic[] {
  const diagnostics: CompileDiagnostic[] = [];
  const totalTokens = items.reduce(
    (sum, item) => sum + (item.tokens ?? estimateTokens(item.content)),
    0
  );
  const maxTokens = budget.maxTokens - (budget.reserveTokens ?? 0);
  const utilization = maxTokens > 0 ? totalTokens / maxTokens : 0;
  const threshold = constraint.threshold ?? 0.7;

  if (utilization < threshold) {
    diagnostics.push({
      level: "warning",
      constraint: "budget-utilization",
      message: `Budget utilization (${Math.round(utilization * 100)}%) is below threshold (${Math.round(threshold * 100)}%)`,
    });
  }

  if (utilization > 0.95) {
    diagnostics.push({
      level: "info",
      constraint: "budget-utilization",
      message: `Budget utilization (${Math.round(utilization * 100)}%) is very high — risk of exceeding budget`,
    });
  }

  return diagnostics;
}

function validateMaxRedundancy(
  items: ContextItem[],
  constraint: Constraint,
  slots: Slot[]
): CompileDiagnostic[] {
  const diagnostics: CompileDiagnostic[] = [];
  const threshold = constraint.threshold ?? 0.5;
  const relevant = itemsForSlots(items, slots, constraint.slots);

  const wordSets = relevant.map(
    item =>
      new Set(
        item.content
          .toLowerCase()
          .split(/\s+/)
          .filter(w => w.length > 2)
      )
  );

  for (let i = 0; i < wordSets.length; i++) {
    for (let j = i + 1; j < wordSets.length; j++) {
      const overlap = wordOverlap(wordSets[i], wordSets[j]);
      if (overlap > threshold) {
        diagnostics.push({
          level: "warning",
          constraint: "max-redundancy",
          message: `Items "${relevant[i].id}" and "${relevant[j].id}" have high overlap (${Math.round(overlap * 100)}%) exceeding threshold (${Math.round(threshold * 100)}%)`,
        });
      }
    }
  }

  return diagnostics;
}

/**
 * Validate a set of packed items against declared constraints.
 *
 * Runs each constraint validator and collects diagnostics.
 */
export function validateConstraints(
  items: ContextItem[],
  constraints: Constraint[],
  slots: Slot[],
  budget: Budget
): CompileDiagnostic[] {
  const diagnostics: CompileDiagnostic[] = [];

  for (const constraint of constraints) {
    switch (constraint.type) {
      case "no-contradiction":
        diagnostics.push(...validateNoContradiction(items, constraint, slots));
        break;
      case "freshness":
        diagnostics.push(...validateFreshness(items, constraint, slots));
        break;
      case "coverage":
        diagnostics.push(...validateCoverage(items, constraint, slots));
        break;
      case "budget-utilization":
        diagnostics.push(
          ...validateBudgetUtilization(items, constraint, slots, budget)
        );
        break;
      case "max-redundancy":
        diagnostics.push(...validateMaxRedundancy(items, constraint, slots));
        break;
    }
  }

  return diagnostics;
}
