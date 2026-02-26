export const MODEL_METADATA = {
  openai: {
    "gpt-4o-mini": { maxTokens: 128000 },
    "gpt-4o": { maxTokens: 128000 },
    "gpt-4.1": { maxTokens: 1048576 },
    "gpt-4.1-mini": { maxTokens: 1048576 },
    "gpt-4.1-nano": { maxTokens: 1048576 },
    o1: { maxTokens: 200000 },
    "o1-mini": { maxTokens: 128000 },
    o3: { maxTokens: 200000 },
    "o3-mini": { maxTokens: 200000 },
    "o4-mini": { maxTokens: 200000 },
  },
  anthropic: {
    "claude-opus-4-6": { maxTokens: 200000 },
    "claude-sonnet-4-6": { maxTokens: 200000 },
    "claude-haiku-4-5-20251001": { maxTokens: 200000 },
    "claude-3-5-sonnet-20241022": { maxTokens: 200000 },
    "claude-3-5-haiku-20241022": { maxTokens: 200000 },
  },
} as const;
