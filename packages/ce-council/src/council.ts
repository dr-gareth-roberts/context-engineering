/**
 * Council of Experts
 *
 * Orchestrates multi-model deliberation with structured debate strategies.
 * Each expert brings a distinct perspective (role + system prompt + model),
 * and the council manages context packing, turn-taking, and synthesis.
 *
 * @example
 * ```ts
 * const council = createCouncil({
 *   members: [
 *     { id: "arch", name: "Architect", role: "system-designer",
 *       systemPrompt: "You are a senior systems architect...",
 *       provider: anthropic, model: "claude-opus-4-6" },
 *     { id: "sec", name: "Security Lead", role: "security-reviewer",
 *       systemPrompt: "You are a security expert...",
 *       provider: openai, model: "gpt-4.1" },
 *     { id: "perf", name: "Performance Engineer", role: "performance-critic",
 *       systemPrompt: "You optimize for latency and throughput...",
 *       provider: anthropic, model: "claude-haiku-4-5" },
 *   ],
 *   strategy: "debate",
 *   rounds: 2,
 *   synthesizer: { provider: anthropic, model: "claude-opus-4-6" },
 * });
 *
 * const result = await council.deliberate({
 *   query: "Should we use microservices or a modular monolith?",
 *   contextItems: architectureDocs,
 *   budget: { maxTokens: 8000 },
 * });
 *
 * console.log(result.synthesis);
 * console.log(result.rounds);
 * console.log(result.totalTokens);
 * ```
 */

import { pack, estimateTokens } from "@context-engineering/core";
import type {
  CouncilConfig,
  DeliberateOptions,
  DeliberationResult,
} from "./types.js";
import { buildSynthesisPrompt } from "./prompts.js";
import {
  executeParallel,
  executeDebate,
  executeStepladder,
  executeDelphi,
} from "./strategies.js";

export interface Council {
  /**
   * Run a full deliberation cycle.
   *
   * 1. Pack context items for each member (if provided)
   * 2. Execute the deliberation strategy across rounds
   * 3. Synthesize a final answer from all perspectives
   */
  deliberate(options: DeliberateOptions): Promise<DeliberationResult>;
}

/**
 * Create a Council of Experts.
 */
export function createCouncil(config: CouncilConfig): Council {
  if (config.members.length < 2) {
    throw new Error("A council requires at least 2 members");
  }

  return {
    async deliberate(options: DeliberateOptions): Promise<DeliberationResult> {
      const start = Date.now();

      // Pack context items into a summary string if provided
      let contextSummary: string | undefined;
      if (options.contextItems && options.budget) {
        const packed = pack(
          options.contextItems,
          options.budget,
          options.packOptions
        );
        contextSummary = packed.selected
          .map(item => item.content)
          .join("\n\n---\n\n");
      } else if (options.contextItems) {
        contextSummary = options.contextItems
          .map(item => item.content)
          .join("\n\n---\n\n");
      }

      // Apply per-call round override
      const effectiveConfig = options.rounds
        ? { ...config, rounds: options.rounds }
        : config;

      // Execute the chosen strategy
      const strategyCtx = {
        config: effectiveConfig,
        query: options.query,
        contextSummary,
      };

      let rounds;
      switch (config.strategy) {
        case "parallel":
          rounds = await executeParallel(strategyCtx);
          break;
        case "debate":
          rounds = await executeDebate(strategyCtx);
          break;
        case "stepladder":
          rounds = await executeStepladder(strategyCtx);
          break;
        case "delphi":
          rounds = await executeDelphi(strategyCtx);
          break;
        default:
          throw new Error(`Unknown strategy: ${config.strategy}`);
      }

      // Synthesize final answer
      const synthesisMessages = buildSynthesisPrompt(
        options.query,
        rounds,
        config.synthesizer.systemPrompt
      );

      const synthesisResult = await config.synthesizer.provider.generate(
        synthesisMessages,
        {
          model: config.synthesizer.model,
          maxTokens: config.synthesizer.maxTokens,
        }
      );

      // Compute token stats
      const tokensByMember: Record<string, number> = {};
      let totalTokens = 0;
      for (const round of rounds) {
        for (const response of round.responses) {
          tokensByMember[response.memberId] =
            (tokensByMember[response.memberId] ?? 0) + response.tokensUsed;
          totalTokens += response.tokensUsed;
        }
      }

      // Add synthesis tokens
      const synthesisTokens =
        synthesisResult.usage?.totalTokens ??
        estimateTokens(synthesisResult.text);
      totalTokens += synthesisTokens;
      tokensByMember["_synthesizer"] = synthesisTokens;

      // Check for early convergence (delphi)
      const lastRound = rounds[rounds.length - 1];
      const convergedEarly =
        config.strategy === "delphi" &&
        lastRound.convergenceScore !== undefined &&
        lastRound.convergenceScore >= (config.convergenceThreshold ?? 0.8) &&
        rounds.length < (config.rounds ?? 3);

      return {
        synthesis: synthesisResult.text,
        synthesisModel: synthesisResult.model,
        rounds,
        totalTokens,
        tokensByMember,
        roundCount: rounds.length,
        strategy: config.strategy,
        convergenceScore: lastRound.convergenceScore,
        convergedEarly,
        durationMs: Date.now() - start,
      };
    },
  };
}

/**
 * Convenience: create a council with common role presets.
 *
 * Provides pre-written system prompts for common expert archetypes.
 */
export const ROLE_PRESETS: Record<
  string,
  { role: string; systemPrompt: string }
> = {
  critic: {
    role: "critic",
    systemPrompt:
      "You are a sharp critical thinker. Your job is to find flaws, edge cases, and unstated assumptions in proposals. Challenge reasoning rigorously but constructively. If something is genuinely good, acknowledge it — but always probe deeper.",
  },
  optimist: {
    role: "optimist",
    systemPrompt:
      "You are an optimistic strategist who identifies opportunities and strengths. Look for what could go right, what advantages exist, and how to maximize upside. Balance enthusiasm with practical reasoning.",
  },
  pragmatist: {
    role: "pragmatist",
    systemPrompt:
      "You are a pragmatic engineer focused on what actually ships. Evaluate ideas by implementation cost, timeline, team capability, and operational risk. Prefer proven approaches over novel ones unless the benefit is clear.",
  },
  innovator: {
    role: "innovator",
    systemPrompt:
      "You are a creative innovator who thinks laterally. Challenge conventional approaches, propose unexpected alternatives, and connect ideas from different domains. Push the group beyond obvious solutions.",
  },
  "domain-expert": {
    role: "domain-expert",
    systemPrompt:
      "You are a deep domain expert. Ground the discussion in technical reality: what works in practice, what the research says, and where theory diverges from real-world experience. Cite specifics over generalities.",
  },
  "devils-advocate": {
    role: "devils-advocate",
    systemPrompt:
      "You are a devil's advocate. Deliberately argue the opposing position to whatever the group consensus appears to be. This is not about being contrarian — it's about stress-testing ideas by forcing the group to defend their reasoning against the strongest possible counterarguments.",
  },
  "user-advocate": {
    role: "user-advocate",
    systemPrompt:
      "You represent the end user. Every proposal should be evaluated through the lens of user experience: Is this intuitive? Does it solve a real problem? Will users actually adopt it? Push back on technical elegance that sacrifices usability.",
  },
  "risk-analyst": {
    role: "risk-analyst",
    systemPrompt:
      "You analyze risk across dimensions: technical, operational, financial, reputational, and regulatory. Quantify likelihood and impact where possible. Propose mitigations for every risk you identify. Separate manageable risks from deal-breakers.",
  },
};
