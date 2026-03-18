import { z } from "zod";
import type { Budget, ContextItem } from "./types.js";
import { ValidationError, BudgetExceededError } from "./errors.js";

export const CompressionSchema = z.object({
  content: z.string(),
  tokens: z.number().nonnegative().finite().optional(),
  note: z.string().optional(),
});

export const ContextItemSchema = z.object({
  id: z.string().min(1, "id must be a non-empty string"),
  content: z.string(),
  kind: z.string().optional(),
  priority: z.number().nonnegative().finite().optional(),
  recency: z.number().nonnegative().finite().optional(),
  tokens: z.number().nonnegative().finite().optional(),
  score: z.number().finite().optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
  compressions: z.array(CompressionSchema).optional(),
  embedding: z.array(z.number().finite()).optional(),
  taskId: z.string().optional(),
  isOutcome: z.boolean().optional(),
  dependsOn: z.array(z.string()).optional(),
});

export const BudgetSchema = z.object({
  maxTokens: z.number().positive("maxTokens must be positive").finite(),
  reserveTokens: z.number().nonnegative().finite().optional(),
});

export const KindAllocationSchema = z.object({
  kind: z.string().min(1),
  targetRatio: z.number().min(0).max(1).optional(),
  minTokens: z.number().int().nonnegative().optional(),
  maxTokens: z.number().int().positive().optional(),
  priority: z.number().int().nonnegative().optional(),
});

export const CacheConfigSchema = z.object({
  provider: z.enum(["anthropic", "openai", "auto"]).optional(),
  minPrefixTokens: z.number().int().nonnegative().optional(),
  markBreakpoints: z.boolean().optional(),
});

export const PlacementOptionsSchema = z.object({
  model: z.string().optional(),
  strategy: z.enum(["score-order", "attention-optimized"]).optional(),
});

export const CompactionOptionsSchema = z.object({
  budget: BudgetSchema,
  summarizeAfterTurns: z.number().int().positive().optional(),
  preserveRecentTurns: z.number().int().nonnegative().optional(),
  systemPrompt: z.string().optional(),
});

/**
 * Generic validation helper that throws a ValidationError on failure.
 *
 * @throws {ValidationError} If data does not match the schema
 */
export function validateWithSchema<T>(
  schema: z.ZodType<T>,
  data: unknown,
  label: string
): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new ValidationError(
      `Invalid ${label}: ${result.error.issues.map((i: z.ZodIssue) => `${i.path.join(".")}: ${i.message}`).join(", ")}`,
      result.error.issues.map((i: z.ZodIssue) => ({
        path: i.path.join("."),
        message: i.message,
      }))
    );
  }
  return result.data;
}

/**
 * Validate pack inputs (items and budget). Shared by pack() and packStream().
 *
 * @throws {ValidationError} If items or budget fail schema validation
 * @throws {BudgetExceededError} If reserveTokens >= maxTokens
 */
export function validatePackInputs(items: ContextItem[], budget: Budget): void {
  const budgetResult = BudgetSchema.safeParse(budget);
  if (!budgetResult.success) {
    throw new ValidationError(
      `Invalid budget: ${budgetResult.error.issues.map((i: z.ZodIssue) => i.message).join(", ")}`,
      budgetResult.error.issues.map((i: z.ZodIssue) => ({
        path: i.path.join("."),
        message: i.message,
      }))
    );
  }

  if (
    budget.reserveTokens !== undefined &&
    budget.reserveTokens >= budget.maxTokens
  ) {
    throw new BudgetExceededError(
      `reserveTokens (${budget.reserveTokens}) must be less than maxTokens (${budget.maxTokens})`
    );
  }

  const itemsResult = z.array(ContextItemSchema).safeParse(items);
  if (!itemsResult.success) {
    throw new ValidationError(
      `Invalid items: ${itemsResult.error.issues.map((i: z.ZodIssue) => `${i.path.join(".")}: ${i.message}`).join(", ")}`,
      itemsResult.error.issues.map((i: z.ZodIssue) => ({
        path: i.path.join("."),
        message: i.message,
      }))
    );
  }
}
