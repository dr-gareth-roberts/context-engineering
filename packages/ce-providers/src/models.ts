export const MODEL_METADATA = {
  openai: {
    "gpt-4o-mini": { maxTokens: 128000 },
    "gpt-4o": { maxTokens: 128000 },
    "o1-mini": { maxTokens: 128000 },
  },
  anthropic: {
    "claude-3-5-sonnet-20241022": { maxTokens: 200000 },
    "claude-3-5-haiku-20241022": { maxTokens: 200000 },
  },
} as const;
