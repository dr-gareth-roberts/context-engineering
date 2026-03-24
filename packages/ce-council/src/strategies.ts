/**
 * Deliberation strategy implementations.
 *
 * Each strategy orchestrates how members interact:
 * - parallel: all respond independently, no interaction
 * - debate: members see each other's responses and iterate
 * - stepladder: members enter one-at-a-time, each seeing prior discussion
 * - delphi: anonymous rounds with convergence detection
 */

import type {
  CouncilMember,
  CouncilConfig,
  MemberResponse,
  DeliberationRound,
} from "./types.js";
import {
  buildInitialPrompt,
  buildDebatePrompt,
  buildStepladderPrompt,
  buildDelphiPrompt,
} from "./prompts.js";
import { computeConvergence } from "./convergence.js";

interface StrategyContext {
  config: CouncilConfig;
  query: string;
  contextSummary?: string;
}

async function callMember(
  member: CouncilMember,
  messages: { role: "system" | "user" | "assistant"; content: string }[]
): Promise<MemberResponse> {
  const result = await member.provider.generate(messages, {
    model: member.model,
    maxTokens: member.maxTokens,
    temperature: member.temperature,
  });
  return {
    memberId: member.id,
    memberName: member.name,
    role: member.role,
    response: result.text,
    model: result.model,
    tokensUsed: result.usage?.totalTokens ?? 0,
  };
}

function emitMemberResponse(
  config: CouncilConfig,
  response: MemberResponse,
  round: number
): void {
  config.onMemberResponse?.({
    memberId: response.memberId,
    memberName: response.memberName,
    round,
    response: response.response,
    tokenCount: response.tokensUsed,
  });
}

function emitRoundComplete(
  config: CouncilConfig,
  round: DeliberationRound,
  totalRounds: number
): void {
  config.onRoundComplete?.({
    round: round.round,
    totalRounds,
    responses: round.responses,
    convergenceScore: round.convergenceScore,
  });
}

/**
 * Parallel strategy: all members respond independently in a single round.
 */
export async function executeParallel(
  ctx: StrategyContext
): Promise<DeliberationRound[]> {
  const { config, query, contextSummary } = ctx;
  const responses = await Promise.all(
    config.members.map(async member => {
      const messages = buildInitialPrompt(
        member.systemPrompt,
        query,
        contextSummary
      );
      const response = await callMember(member, messages);
      emitMemberResponse(config, response, 1);
      return response;
    })
  );

  const round: DeliberationRound = { round: 1, responses };
  emitRoundComplete(config, round, 1);
  return [round];
}

/**
 * Debate strategy: members see each other's responses and iterate.
 */
export async function executeDebate(
  ctx: StrategyContext
): Promise<DeliberationRound[]> {
  const { config, query, contextSummary } = ctx;
  const rounds: DeliberationRound[] = [];
  const numRounds = config.rounds ?? 2;

  // Round 1: independent responses (same as parallel)
  const initialResponses = await Promise.all(
    config.members.map(async member => {
      const messages = buildInitialPrompt(
        member.systemPrompt,
        query,
        contextSummary
      );
      const response = await callMember(member, messages);
      emitMemberResponse(config, response, 1);
      return response;
    })
  );

  const firstRound: DeliberationRound = {
    round: 1,
    responses: initialResponses,
  };
  emitRoundComplete(config, firstRound, numRounds);
  rounds.push(firstRound);

  // Subsequent rounds: each member sees all others' previous responses
  for (let r = 2; r <= numRounds; r++) {
    const prevResponses = rounds[rounds.length - 1].responses;
    const roundResponses = await Promise.all(
      config.members.map(async member => {
        // Show this member everyone else's responses from the previous round
        const othersResponses = prevResponses.filter(
          resp => resp.memberId !== member.id
        );
        const messages = buildDebatePrompt(
          member.systemPrompt,
          query,
          othersResponses,
          r,
          contextSummary
        );
        const response = await callMember(member, messages);
        emitMemberResponse(config, response, r);
        return response;
      })
    );

    const round: DeliberationRound = { round: r, responses: roundResponses };
    emitRoundComplete(config, round, numRounds);
    rounds.push(round);
  }

  return rounds;
}

/**
 * Stepladder strategy: members enter one at a time, each seeing the prior discussion.
 *
 * Based on the Stepladder Technique (Rogelberg et al., 1992):
 * 1. First two members discuss independently
 * 2. Third member enters, sees the discussion, adds their view
 * 3. Continue until all members have contributed
 *
 * This prevents anchoring bias — each new member forms their opinion
 * before seeing the group's, then integrates both.
 */
export async function executeStepladder(
  ctx: StrategyContext
): Promise<DeliberationRound[]> {
  const { config, query, contextSummary } = ctx;
  const rounds: DeliberationRound[] = [];
  const allResponses: MemberResponse[] = [];

  for (let i = 0; i < config.members.length; i++) {
    const member = config.members[i];
    const messages =
      i === 0
        ? buildInitialPrompt(member.systemPrompt, query, contextSummary)
        : buildStepladderPrompt(
            member.systemPrompt,
            query,
            allResponses,
            contextSummary
          );

    const response = await callMember(member, messages);
    allResponses.push(response);
    emitMemberResponse(config, response, i + 1);

    const round: DeliberationRound = {
      round: i + 1,
      responses: [...allResponses],
    };
    emitRoundComplete(config, round, config.members.length);
    rounds.push(round);
  }

  return rounds;
}

/**
 * Delphi strategy: anonymous rounds with convergence detection.
 *
 * Based on the Delphi method (RAND Corporation, 1950s):
 * 1. All members respond independently (anonymous)
 * 2. Responses are shared without attribution
 * 3. Members revise their positions
 * 4. Repeat until convergence or max rounds
 *
 * Anonymity prevents authority bias and groupthink.
 */
export async function executeDelphi(
  ctx: StrategyContext
): Promise<DeliberationRound[]> {
  const { config, query, contextSummary } = ctx;
  const rounds: DeliberationRound[] = [];
  const numRounds = config.rounds ?? 3;
  const convergenceThreshold = config.convergenceThreshold ?? 0.8;

  // Round 1: independent anonymous responses
  const initialResponses = await Promise.all(
    config.members.map(async member => {
      const messages = buildInitialPrompt(
        member.systemPrompt,
        query,
        contextSummary
      );
      const response = await callMember(member, messages);
      emitMemberResponse(config, response, 1);
      return response;
    })
  );

  const convergence = computeConvergence(initialResponses);
  const firstRound: DeliberationRound = {
    round: 1,
    responses: initialResponses,
    convergenceScore: convergence,
  };
  emitRoundComplete(config, firstRound, numRounds);
  rounds.push(firstRound);

  if (convergence >= convergenceThreshold) {
    return rounds;
  }

  // Subsequent rounds: anonymous sharing with convergence check
  for (let r = 2; r <= numRounds; r++) {
    const prevResponses = rounds[rounds.length - 1].responses;
    const roundResponses = await Promise.all(
      config.members.map(async member => {
        const messages = buildDelphiPrompt(
          member.systemPrompt,
          query,
          prevResponses,
          r,
          contextSummary
        );
        const response = await callMember(member, messages);
        emitMemberResponse(config, response, r);
        return response;
      })
    );

    const roundConvergence = computeConvergence(roundResponses);
    const round: DeliberationRound = {
      round: r,
      responses: roundResponses,
      convergenceScore: roundConvergence,
    };
    emitRoundComplete(config, round, numRounds);
    rounds.push(round);

    if (roundConvergence >= convergenceThreshold) {
      break;
    }
  }

  return rounds;
}
