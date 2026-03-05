import { z } from "zod";

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
  taskId: z.string().optional(),
  isOutcome: z.boolean().optional(),
  dependsOn: z.array(z.string()).optional(),
});

export const BudgetSchema = z.object({
  maxTokens: z.number().positive("maxTokens must be positive").finite(),
  reserveTokens: z.number().nonnegative().finite().optional(),
});

export const PackOptionsSchema = z
  .object({
    tokenEstimator: z.function().optional(),
    scorer: z.function().optional(),
    summarizer: z.function().optional(),
    allowCompression: z.boolean().optional(),
  })
  .optional();
