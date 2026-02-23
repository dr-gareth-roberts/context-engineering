import { z } from "zod";

export const CompressionSchema = z.object({
  content: z.string(),
  tokens: z.number().nonnegative().optional(),
  note: z.string().optional(),
});

export const ContextItemSchema = z.object({
  id: z.string().min(1, "id must be a non-empty string"),
  content: z.string(),
  kind: z.string().optional(),
  priority: z.number().nonnegative().optional(),
  recency: z.number().nonnegative().optional(),
  tokens: z.number().nonnegative().optional(),
  score: z.number().optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
  compressions: z.array(CompressionSchema).optional(),
});

export const BudgetSchema = z.object({
  maxTokens: z.number().positive("maxTokens must be positive"),
  reserveTokens: z.number().nonnegative().optional(),
});

export const PackOptionsSchema = z
  .object({
    tokenEstimator: z.function().optional(),
    scorer: z.function().optional(),
    summarizer: z.function().optional(),
    allowCompression: z.boolean().optional(),
  })
  .optional();
