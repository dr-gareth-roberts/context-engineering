"""
Council of Experts — multi-model deliberation with structured debate strategies.

Strategies:
- parallel: all experts respond independently, synthesizer merges
- debate: experts see each other's responses and iterate in rounds
- stepladder: experts enter one at a time, each seeing prior discussion
- delphi: anonymous rounds with convergence detection
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .core import Budget, ContextItem, pack

# ---------------------------------------------------------------------------
# Provider protocol — duck-typed, no hard dependency on ce-providers
# ---------------------------------------------------------------------------


class CouncilLLMProvider(Protocol):
    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class CouncilMember:
    id: str
    name: str
    role: str
    system_prompt: str
    provider: CouncilLLMProvider
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class MemberResponse:
    member_id: str
    member_name: str
    role: str
    response: str
    model: str
    tokens_used: int


@dataclass
class DeliberationRound:
    round: int
    responses: list[MemberResponse]
    convergence_score: float | None = None


@dataclass
class DeliberationResult:
    synthesis: str
    synthesis_model: str
    rounds: list[DeliberationRound]
    total_tokens: int
    tokens_by_member: dict[str, int]
    round_count: int
    strategy: str
    convergence_score: float | None = None
    converged_early: bool = False
    duration_ms: int = 0


@dataclass
class SynthesizerConfig:
    provider: CouncilLLMProvider
    model: str | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None


@dataclass
class CouncilConfig:
    members: list[CouncilMember]
    strategy: str  # "parallel" | "debate" | "stepladder" | "delphi"
    synthesizer: SynthesizerConfig
    rounds: int = 2
    convergence_threshold: float = 0.8
    on_member_response: Callable[..., None] | None = None
    on_round_complete: Callable[..., None] | None = None


# ---------------------------------------------------------------------------
# Convergence
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    import re

    return {
        w for w in re.split(r'[\s.,;:!?(){}[\]"\'`~@#$%^&*+=|\\/<>-]+', text.lower()) if len(w) > 2
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def compute_convergence(responses: list[MemberResponse]) -> float:
    """Average pairwise Jaccard similarity across all member responses."""
    if len(responses) < 2:
        return 1.0
    token_sets = [_tokenize(r.response) for r in responses]
    total = 0.0
    count = 0
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            total += _jaccard(token_sets[i], token_sets[j])
            count += 1
    return total / count if count else 1.0


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _initial_messages(
    system_prompt: str, query: str, context: str | None = None
) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    if context:
        msgs.append({"role": "user", "content": f"Context:\n{context}\n\n---\n\nQuestion: {query}"})
    else:
        msgs.append({"role": "user", "content": query})
    return msgs


def _debate_messages(
    system_prompt: str,
    query: str,
    prior: list[MemberResponse],
    round_num: int,
    context: str | None = None,
) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    parts = []
    if context:
        parts.append(f"Context:\n{context}\n\n---\n")
    parts.append(f"Question: {query}\n\n---\n\nRound {round_num}. Previous responses:\n")
    for r in prior:
        parts.append(f"**{r.member_name}** ({r.role}):\n{r.response}\n")
    parts.append(
        "---\nProvide your updated analysis. Be specific about agreements and disagreements."
    )
    msgs.append({"role": "user", "content": "\n".join(parts)})
    return msgs


def _stepladder_messages(
    system_prompt: str, query: str, prior: list[MemberResponse], context: str | None = None
) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    parts = []
    if context:
        parts.append(f"Context:\n{context}\n\n---\n")
    parts.append(f"Question: {query}\n")
    if prior:
        parts.append("\n---\nPrior discussion:\n")
        for r in prior:
            parts.append(f"**{r.member_name}** ({r.role}):\n{r.response}\n")
        parts.append("---\nAdd your fresh perspective, then engage with the points above.")
    msgs.append({"role": "user", "content": "\n".join(parts)})
    return msgs


def _delphi_messages(
    system_prompt: str,
    query: str,
    prior: list[MemberResponse],
    round_num: int,
    context: str | None = None,
) -> list[dict[str, str]]:
    msgs: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    parts = []
    if context:
        parts.append(f"Context:\n{context}\n\n---\n")
    parts.append(f"Question: {query}\n\n---\n\nAnonymous round {round_num}:\n")
    for i, r in enumerate(prior, 1):
        parts.append(f"**Expert {i}**:\n{r.response}\n")
    parts.append("---\nRefine your analysis. Build consensus where possible.")
    msgs.append({"role": "user", "content": "\n".join(parts)})
    return msgs


def _synthesis_messages(
    query: str, rounds: list[DeliberationRound], custom_prompt: str | None = None
) -> list[dict[str, str]]:
    system = custom_prompt or (
        "You are a synthesis expert. Produce a single authoritative answer by combining "
        "the best insights from multiple expert perspectives. Preserve nuance where experts "
        "genuinely disagree, but converge on clear recommendations where consensus exists."
    )
    last = rounds[-1]
    parts = [f"Question: {query}\n\n---\n\nExperts deliberated over {len(rounds)} round(s):\n"]
    for r in last.responses:
        parts.append(f"**{r.member_name}** ({r.role}):\n{r.response}\n")
    parts.append("---\nSynthesize into a single well-structured answer.")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(parts)},
    ]


# ---------------------------------------------------------------------------
# Provider call helper
# ---------------------------------------------------------------------------


async def _call_member(member: CouncilMember, messages: list[dict[str, str]]) -> MemberResponse:
    result = await member.provider.generate(
        messages, model=member.model, max_tokens=member.max_tokens, temperature=member.temperature
    )
    return MemberResponse(
        member_id=member.id,
        member_name=member.name,
        role=member.role,
        response=result.get("text", ""),
        model=result.get("model", "unknown"),
        tokens_used=result.get("usage", {}).get("total_tokens", 0)
        if isinstance(result.get("usage"), dict)
        else 0,
    )


# ---------------------------------------------------------------------------
# Strategy executors
# ---------------------------------------------------------------------------


async def _parallel(config: CouncilConfig, query: str, ctx: str | None) -> list[DeliberationRound]:
    import asyncio

    responses = await asyncio.gather(
        *(_call_member(m, _initial_messages(m.system_prompt, query, ctx)) for m in config.members)
    )
    rnd = DeliberationRound(round=1, responses=list(responses))
    return [rnd]


async def _debate(config: CouncilConfig, query: str, ctx: str | None) -> list[DeliberationRound]:
    import asyncio

    rounds: list[DeliberationRound] = []

    # Round 1: independent
    r1 = await asyncio.gather(
        *(_call_member(m, _initial_messages(m.system_prompt, query, ctx)) for m in config.members)
    )
    rounds.append(DeliberationRound(round=1, responses=list(r1)))

    for r in range(2, config.rounds + 1):
        prev = rounds[-1].responses
        responses = await asyncio.gather(
            *(
                _call_member(
                    m,
                    _debate_messages(
                        m.system_prompt, query, [p for p in prev if p.member_id != m.id], r, ctx
                    ),
                )
                for m in config.members
            )
        )
        rounds.append(DeliberationRound(round=r, responses=list(responses)))

    return rounds


async def _stepladder(
    config: CouncilConfig, query: str, ctx: str | None
) -> list[DeliberationRound]:
    rounds: list[DeliberationRound] = []
    all_responses: list[MemberResponse] = []

    for i, m in enumerate(config.members):
        if i == 0:
            msgs = _initial_messages(m.system_prompt, query, ctx)
        else:
            msgs = _stepladder_messages(m.system_prompt, query, all_responses, ctx)
        resp = await _call_member(m, msgs)
        all_responses.append(resp)
        rounds.append(DeliberationRound(round=i + 1, responses=list(all_responses)))

    return rounds


async def _delphi(config: CouncilConfig, query: str, ctx: str | None) -> list[DeliberationRound]:
    import asyncio

    rounds: list[DeliberationRound] = []

    r1 = await asyncio.gather(
        *(_call_member(m, _initial_messages(m.system_prompt, query, ctx)) for m in config.members)
    )
    conv = compute_convergence(list(r1))
    rounds.append(DeliberationRound(round=1, responses=list(r1), convergence_score=conv))

    if conv >= config.convergence_threshold:
        return rounds

    for r in range(2, config.rounds + 1):
        prev = rounds[-1].responses
        responses = await asyncio.gather(
            *(
                _call_member(m, _delphi_messages(m.system_prompt, query, prev, r, ctx))
                for m in config.members
            )
        )
        conv = compute_convergence(list(responses))
        rounds.append(DeliberationRound(round=r, responses=list(responses), convergence_score=conv))
        if conv >= config.convergence_threshold:
            break

    return rounds


# ---------------------------------------------------------------------------
# Council
# ---------------------------------------------------------------------------


async def deliberate(
    config: CouncilConfig,
    *,
    query: str,
    context_items: list[ContextItem] | None = None,
    budget: Budget | None = None,
) -> DeliberationResult:
    """Run a full council deliberation."""
    if len(config.members) < 2:
        raise ValueError("A council requires at least 2 members")

    start = time.monotonic()

    # Pack context
    ctx_summary: str | None = None
    if context_items and budget:
        packed = pack(context_items, budget)
        ctx_summary = "\n\n---\n\n".join(i.content for i in packed.selected)
    elif context_items:
        ctx_summary = "\n\n---\n\n".join(i.content for i in context_items)

    executors = {
        "parallel": _parallel,
        "debate": _debate,
        "stepladder": _stepladder,
        "delphi": _delphi,
    }
    executor = executors.get(config.strategy)
    if not executor:
        raise ValueError(f"Unknown strategy: {config.strategy}")

    rounds = await executor(config, query, ctx_summary)

    # Synthesize
    synth_msgs = _synthesis_messages(query, rounds, config.synthesizer.system_prompt)
    synth_result = await config.synthesizer.provider.generate(
        synth_msgs, model=config.synthesizer.model, max_tokens=config.synthesizer.max_tokens
    )

    tokens_by_member: dict[str, int] = {}
    total_tokens = 0
    for rnd in rounds:
        for resp in rnd.responses:
            tokens_by_member[resp.member_id] = (
                tokens_by_member.get(resp.member_id, 0) + resp.tokens_used
            )
            total_tokens += resp.tokens_used

    synth_tokens = (
        synth_result.get("usage", {}).get("total_tokens", 0)
        if isinstance(synth_result.get("usage"), dict)
        else 0
    )
    total_tokens += synth_tokens
    tokens_by_member["_synthesizer"] = synth_tokens

    last = rounds[-1]
    converged_early = (
        config.strategy == "delphi"
        and last.convergence_score is not None
        and last.convergence_score >= config.convergence_threshold
        and len(rounds) < config.rounds
    )

    return DeliberationResult(
        synthesis=synth_result.get("text", ""),
        synthesis_model=synth_result.get("model", "unknown"),
        rounds=rounds,
        total_tokens=total_tokens,
        tokens_by_member=tokens_by_member,
        round_count=len(rounds),
        strategy=config.strategy,
        convergence_score=last.convergence_score,
        converged_early=converged_early,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def create_council(config: CouncilConfig):
    """Create a council object with a deliberate() method."""

    class Council:
        async def deliberate(
            self,
            *,
            query: str,
            context_items: list[ContextItem] | None = None,
            budget: Budget | None = None,
        ) -> DeliberationResult:
            return await globals()["deliberate"](
                config, query=query, context_items=context_items, budget=budget
            )

    return Council()


# ---------------------------------------------------------------------------
# Role presets
# ---------------------------------------------------------------------------

ROLE_PRESETS: dict[str, dict[str, str]] = {
    "critic": {
        "role": "critic",
        "system_prompt": "You are a sharp critical thinker. Find flaws, edge cases, and unstated assumptions. Challenge reasoning rigorously but constructively.",
    },
    "optimist": {
        "role": "optimist",
        "system_prompt": "You are an optimistic strategist who identifies opportunities and strengths. Look for what could go right and how to maximize upside.",
    },
    "pragmatist": {
        "role": "pragmatist",
        "system_prompt": "You are a pragmatic engineer focused on what actually ships. Evaluate by implementation cost, timeline, and operational risk.",
    },
    "innovator": {
        "role": "innovator",
        "system_prompt": "You are a creative innovator who thinks laterally. Challenge conventional approaches and propose unexpected alternatives.",
    },
    "domain-expert": {
        "role": "domain-expert",
        "system_prompt": "You are a deep domain expert. Ground the discussion in technical reality and cite specifics over generalities.",
    },
    "devils-advocate": {
        "role": "devils-advocate",
        "system_prompt": "You are a devil's advocate. Argue the opposing position to stress-test ideas by forcing the group to defend their reasoning.",
    },
    "user-advocate": {
        "role": "user-advocate",
        "system_prompt": "You represent the end user. Evaluate every proposal through the lens of user experience and real-world adoption.",
    },
    "risk-analyst": {
        "role": "risk-analyst",
        "system_prompt": "You analyze risk across technical, operational, financial, and regulatory dimensions. Quantify likelihood and impact.",
    },
}
