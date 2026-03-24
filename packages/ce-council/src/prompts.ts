/**
 * Prompt templates for council deliberation.
 *
 * Each strategy has distinct prompting needs — debate members need
 * to see prior responses, stepladder members enter progressively,
 * and delphi members must respond anonymously.
 */

import type { CouncilMessage, MemberResponse } from "./types.js";

/**
 * Build the initial prompt for a member's first-round response.
 */
export function buildInitialPrompt(
  systemPrompt: string,
  query: string,
  contextSummary?: string
): CouncilMessage[] {
  const messages: CouncilMessage[] = [
    { role: "system", content: systemPrompt },
  ];

  if (contextSummary) {
    messages.push({
      role: "user",
      content: `Here is the relevant context:\n\n${contextSummary}\n\n---\n\nQuestion: ${query}`,
    });
  } else {
    messages.push({ role: "user", content: query });
  }

  return messages;
}

/**
 * Build a debate prompt that includes prior round responses.
 */
export function buildDebatePrompt(
  systemPrompt: string,
  query: string,
  priorResponses: MemberResponse[],
  round: number,
  contextSummary?: string
): CouncilMessage[] {
  const messages: CouncilMessage[] = [
    { role: "system", content: systemPrompt },
  ];

  let content = "";
  if (contextSummary) {
    content += `Context:\n${contextSummary}\n\n---\n\n`;
  }
  content += `Question: ${query}\n\n`;
  content += `---\n\nThis is round ${round} of deliberation. Here are the other experts' responses from the previous round:\n\n`;

  for (const r of priorResponses) {
    content += `**${r.memberName}** (${r.role}):\n${r.response}\n\n`;
  }

  content += `---\n\nConsidering the above perspectives, provide your updated analysis. You may refine your position, challenge others' reasoning, or identify points of agreement. Be specific about where you agree or disagree and why.`;

  messages.push({ role: "user", content });
  return messages;
}

/**
 * Build a stepladder prompt where the member sees the running discussion.
 */
export function buildStepladderPrompt(
  systemPrompt: string,
  query: string,
  discussionSoFar: MemberResponse[],
  contextSummary?: string
): CouncilMessage[] {
  const messages: CouncilMessage[] = [
    { role: "system", content: systemPrompt },
  ];

  let content = "";
  if (contextSummary) {
    content += `Context:\n${contextSummary}\n\n---\n\n`;
  }
  content += `Question: ${query}\n\n`;

  if (discussionSoFar.length > 0) {
    content += `---\n\nThe following experts have already weighed in:\n\n`;
    for (const r of discussionSoFar) {
      content += `**${r.memberName}** (${r.role}):\n${r.response}\n\n`;
    }
    content += `---\n\nYou are joining this discussion as a fresh perspective. Provide your independent analysis, then engage with the points raised above. Highlight anything the group may have missed.`;
  }

  messages.push({ role: "user", content });
  return messages;
}

/**
 * Build an anonymous delphi prompt (no attribution of prior responses).
 */
export function buildDelphiPrompt(
  systemPrompt: string,
  query: string,
  priorResponses: MemberResponse[],
  round: number,
  contextSummary?: string
): CouncilMessage[] {
  const messages: CouncilMessage[] = [
    { role: "system", content: systemPrompt },
  ];

  let content = "";
  if (contextSummary) {
    content += `Context:\n${contextSummary}\n\n---\n\n`;
  }
  content += `Question: ${query}\n\n`;
  content += `---\n\nThis is round ${round} of an anonymous expert panel. Here are the anonymized responses from the previous round:\n\n`;

  priorResponses.forEach((r, i) => {
    content += `**Expert ${i + 1}**:\n${r.response}\n\n`;
  });

  content += `---\n\nConsidering these perspectives, provide your refined analysis. Focus on building consensus where possible and clearly flagging remaining disagreements with reasoning.`;

  messages.push({ role: "user", content });
  return messages;
}

/**
 * Build the synthesis prompt that merges all deliberation into a final answer.
 */
export function buildSynthesisPrompt(
  query: string,
  rounds: { round: number; responses: MemberResponse[] }[],
  customSystemPrompt?: string
): CouncilMessage[] {
  const systemPrompt =
    customSystemPrompt ??
    `You are a synthesis expert. Your job is to produce a single, authoritative answer by combining the best insights from multiple expert perspectives. Preserve nuance where experts genuinely disagree, but converge on clear recommendations where consensus exists. Structure your response clearly.`;

  const messages: CouncilMessage[] = [
    { role: "system", content: systemPrompt },
  ];

  let content = `Question: ${query}\n\n---\n\n`;
  content += `The following experts deliberated over ${rounds.length} round(s):\n\n`;

  const lastRound = rounds[rounds.length - 1];
  if (lastRound) {
    for (const r of lastRound.responses) {
      content += `**${r.memberName}** (${r.role}):\n${r.response}\n\n`;
    }
  }

  if (rounds.length > 1) {
    content += `---\n\nKey evolution across rounds:\n\n`;
    for (const round of rounds) {
      content += `Round ${round.round}: ${round.responses.map(r => `${r.memberName} focused on ${r.response.slice(0, 80)}...`).join("; ")}\n`;
    }
    content += "\n";
  }

  content += `---\n\nSynthesize these perspectives into a single, well-structured answer. Where experts agree, state the consensus clearly. Where they disagree, explain the trade-offs and recommend a path forward.`;

  messages.push({ role: "user", content });
  return messages;
}
