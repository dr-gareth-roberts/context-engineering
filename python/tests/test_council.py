"""Tests for the Council of Experts module."""

import pytest

from context_engineering.council import (
    ROLE_PRESETS,
    CouncilConfig,
    CouncilMember,
    MemberResponse,
    SynthesizerConfig,
    compute_convergence,
    deliberate,
)

# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockProvider:
    def __init__(self, prefix: str = "response"):
        self.call_count = 0
        self.prefix = prefix

    async def generate(self, messages, *, model=None, max_tokens=None, temperature=None):
        self.call_count += 1
        return {
            "text": f"{self.prefix}-{self.call_count}",
            "model": model or "mock",
            "usage": {"total_tokens": 50},
        }


def make_member(id: str, role: str, provider=None) -> CouncilMember:
    return CouncilMember(
        id=id,
        name=id.capitalize(),
        role=role,
        system_prompt=f"You are a {role}.",
        provider=provider or MockProvider(id),
    )


def make_config(**overrides) -> CouncilConfig:
    synth = MockProvider("synthesis")
    defaults = dict(
        members=[make_member("alice", "critic"), make_member("bob", "optimist")],
        strategy="parallel",
        synthesizer=SynthesizerConfig(provider=synth),
    )
    defaults.update(overrides)
    return CouncilConfig(**defaults)


# ---------------------------------------------------------------------------
# Convergence tests
# ---------------------------------------------------------------------------


class TestConvergence:
    def _resp(self, text: str, id: str = "m1") -> MemberResponse:
        return MemberResponse(
            member_id=id,
            member_name="Test",
            role="test",
            response=text,
            model="test",
            tokens_used=0,
        )

    def test_single_response(self):
        assert compute_convergence([self._resp("hello")]) == 1.0

    def test_identical_responses(self):
        score = compute_convergence(
            [
                self._resp("microservices are the best approach for scalable systems", "a"),
                self._resp("microservices are the best approach for scalable systems", "b"),
            ]
        )
        assert score == 1.0

    def test_similar_beats_dissimilar(self):
        similar = compute_convergence(
            [
                self._resp("microservices provide better scalability and isolation", "a"),
                self._resp("microservices offer better scalability and service isolation", "b"),
            ]
        )
        dissimilar = compute_convergence(
            [
                self._resp("the database schema needs normalization and indexing", "a"),
                self._resp("frontend components should use react hooks with memoization", "b"),
            ]
        )
        assert similar > dissimilar

    def test_empty(self):
        assert compute_convergence([]) == 1.0


# ---------------------------------------------------------------------------
# Strategy tests
# ---------------------------------------------------------------------------


class TestParallel:
    @pytest.mark.asyncio
    async def test_produces_synthesis(self):
        config = make_config(strategy="parallel")
        result = await deliberate(config, query="What is X?")
        assert "synthesis" in result.synthesis
        assert result.round_count == 1
        assert len(result.rounds) == 1
        assert len(result.rounds[0].responses) == 2
        assert result.strategy == "parallel"
        assert result.total_tokens > 0

    @pytest.mark.asyncio
    async def test_calls_each_member_once(self):
        p1 = MockProvider("alice")
        p2 = MockProvider("bob")
        config = make_config(
            strategy="parallel",
            members=[make_member("alice", "critic", p1), make_member("bob", "optimist", p2)],
        )
        await deliberate(config, query="What is X?")
        assert p1.call_count == 1
        assert p2.call_count == 1


class TestDebate:
    @pytest.mark.asyncio
    async def test_multiple_rounds(self):
        config = make_config(strategy="debate", rounds=2)
        result = await deliberate(config, query="Debate this.")
        assert result.round_count == 2
        assert len(result.rounds) == 2
        assert len(result.rounds[0].responses) == 2
        assert len(result.rounds[1].responses) == 2


class TestStepladder:
    @pytest.mark.asyncio
    async def test_adds_members_incrementally(self):
        config = make_config(
            strategy="stepladder",
            members=[
                make_member("a", "critic"),
                make_member("b", "optimist"),
                make_member("c", "pragmatist"),
            ],
        )
        result = await deliberate(config, query="Step by step.")
        assert result.round_count == 3
        assert len(result.rounds[0].responses) == 1
        assert len(result.rounds[1].responses) == 2
        assert len(result.rounds[2].responses) == 3


class TestDelphi:
    @pytest.mark.asyncio
    async def test_runs_anonymous_rounds(self):
        config = make_config(strategy="delphi", rounds=3)
        result = await deliberate(config, query="Anonymous debate.")
        assert result.strategy == "delphi"
        assert result.convergence_score is not None

    @pytest.mark.asyncio
    async def test_converges_early_on_identical_responses(self):
        identical = MockProvider("same")

        # Override to always return the same text
        async def _same_gen(messages, *, model=None, max_tokens=None, temperature=None):
            return {
                "text": "exactly the same response with enough words to converge",
                "model": "mock",
                "usage": {"total_tokens": 20},
            }

        identical.generate = _same_gen

        config = CouncilConfig(
            members=[
                make_member("a", "critic", identical),
                make_member("b", "optimist", identical),
            ],
            strategy="delphi",
            synthesizer=SynthesizerConfig(provider=identical),
            rounds=5,
            convergence_threshold=0.8,
        )
        result = await deliberate(config, query="Agree?")
        assert result.converged_early is True
        assert result.round_count == 1


class TestContextPacking:
    @pytest.mark.asyncio
    async def test_packs_context_items_with_budget(self):
        from context_engineering.core import Budget, ContextItem

        config = make_config(strategy="parallel")
        result = await deliberate(
            config,
            query="Analyze this.",
            context_items=[
                ContextItem(id="doc1", content="Important document", priority=10),
                ContextItem(id="doc2", content="Supporting evidence", priority=5),
            ],
            budget=Budget(max_tokens=1000),
        )
        assert result.synthesis is not None


class TestTokenTracking:
    @pytest.mark.asyncio
    async def test_tracks_tokens(self):
        config = make_config(strategy="debate", rounds=2)
        result = await deliberate(config, query="Track tokens.")
        assert result.total_tokens > 0
        assert "alice" in result.tokens_by_member
        assert "bob" in result.tokens_by_member
        assert "_synthesizer" in result.tokens_by_member


class TestRolePresets:
    def test_all_presets_have_required_fields(self):
        expected = {
            "critic",
            "optimist",
            "pragmatist",
            "innovator",
            "domain-expert",
            "devils-advocate",
            "user-advocate",
            "risk-analyst",
        }
        assert set(ROLE_PRESETS.keys()) == expected
        for preset in ROLE_PRESETS.values():
            assert "role" in preset
            assert "system_prompt" in preset
            assert len(preset["system_prompt"]) > 20


class TestValidation:
    @pytest.mark.asyncio
    async def test_rejects_single_member(self):
        config = CouncilConfig(
            members=[make_member("solo", "critic")],
            strategy="parallel",
            synthesizer=SynthesizerConfig(provider=MockProvider()),
        )
        with pytest.raises(ValueError, match="at least 2"):
            await deliberate(config, query="Solo?")
