import type {
  ContextItem,
  Budget,
  PackOptions,
} from "@context-engineering/core";

/**
 * A provider that can generate text from messages.
 * Matches the LLMProvider interface from ce-providers without importing it,
 * so ce-council has zero provider dependencies.
 */
export interface CouncilLLMProvider {
  generate(
    messages: CouncilMessage[],
    options?: { model?: string; maxTokens?: number; temperature?: number }
  ): Promise<{ text: string; model: string; usage?: { totalTokens?: number } }>;
}

export interface CouncilMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

/**
 * A member of the council — an expert with a distinct perspective.
 */
export interface CouncilMember {
  /** Unique identifier for this member */
  id: string;
  /** Display name */
  name: string;
  /** The role/perspective this expert brings (e.g., "critic", "optimist", "domain-expert") */
  role: string;
  /** System prompt defining this expert's perspective and behavior */
  systemPrompt: string;
  /** LLM provider for this member */
  provider: CouncilLLMProvider;
  /** Model to use (passed to provider.generate) */
  model?: string;
  /** Temperature for this member's responses */
  temperature?: number;
  /** Max tokens for this member's responses */
  maxTokens?: number;
}

/** Deliberation strategies */
export type CouncilStrategy = "parallel" | "debate" | "stepladder" | "delphi";

/**
 * Configuration for creating a council.
 */
export interface CouncilConfig {
  /** The experts in this council */
  members: CouncilMember[];
  /** Deliberation strategy */
  strategy: CouncilStrategy;
  /** Number of debate rounds (for debate/delphi strategies) */
  rounds?: number;
  /** The synthesizer produces the final merged answer */
  synthesizer: {
    provider: CouncilLLMProvider;
    model?: string;
    maxTokens?: number;
    /** Custom synthesis prompt (receives all member responses) */
    systemPrompt?: string;
  };
  /** Convergence threshold for delphi strategy (0-1). Stops early if agreement exceeds this. */
  convergenceThreshold?: number;
  /** Called after each member responds in each round */
  onMemberResponse?: (event: MemberResponseEvent) => void;
  /** Called after each round completes */
  onRoundComplete?: (event: RoundCompleteEvent) => void;
}

export interface MemberResponseEvent {
  memberId: string;
  memberName: string;
  round: number;
  response: string;
  tokenCount: number;
}

export interface RoundCompleteEvent {
  round: number;
  totalRounds: number;
  responses: MemberResponse[];
  convergenceScore?: number;
}

/**
 * A single member's response in a round.
 */
export interface MemberResponse {
  memberId: string;
  memberName: string;
  role: string;
  response: string;
  model: string;
  tokensUsed: number;
}

/**
 * A complete round of deliberation.
 */
export interface DeliberationRound {
  round: number;
  responses: MemberResponse[];
  convergenceScore?: number;
}

/**
 * The final result of council deliberation.
 */
export interface DeliberationResult {
  /** The synthesized final answer */
  synthesis: string;
  /** Model used for synthesis */
  synthesisModel: string;
  /** All deliberation rounds */
  rounds: DeliberationRound[];
  /** Total tokens consumed across all members and rounds */
  totalTokens: number;
  /** Per-member token breakdown */
  tokensByMember: Record<string, number>;
  /** Number of rounds executed */
  roundCount: number;
  /** Strategy used */
  strategy: CouncilStrategy;
  /** Final convergence score (delphi only) */
  convergenceScore?: number;
  /** Whether the council converged early (delphi only) */
  convergedEarly?: boolean;
  /** Timing in milliseconds */
  durationMs: number;
}

/**
 * Options for a single deliberation call.
 */
export interface DeliberateOptions {
  /** The query/question for the council to deliberate on */
  query: string;
  /** Context items to pack for each member */
  contextItems?: ContextItem[];
  /** Token budget for context packing */
  budget?: Budget;
  /** Pack options for context */
  packOptions?: PackOptions;
  /** Override number of rounds for this call */
  rounds?: number;
}
