export interface LLMMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface LLMGenerationOptions {
  model?: string;
  maxTokens?: number;
  temperature?: number;
}

export interface LLMUsage {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
}

export interface LLMResult {
  text: string;
  model: string;
  usage?: LLMUsage;
}

export interface LLMProvider {
  generate(
    messages: LLMMessage[],
    options?: LLMGenerationOptions
  ): Promise<LLMResult>;
}

export interface EmbeddingOptions {
  model?: string;
}

export interface EmbeddingResult {
  vectors: number[][];
  model: string;
}

export interface EmbeddingProvider {
  embed(
    inputs: string[] | string,
    options?: EmbeddingOptions
  ): Promise<EmbeddingResult>;
}
