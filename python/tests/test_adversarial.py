"""Tests for the Adversarial Context Tester module."""

import pytest

from context_engineering.adversarial import (
    ALL_ATTACK_TYPES,
    AdversarialConfig,
    AttackConfig,
    ProbeReport,
    apply_attack,
    count_injected,
    create_adversarial_tester,
    describe_attack,
)
from context_engineering.core import Budget, ContextItem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_items(count: int) -> list[ContextItem]:
    return [
        ContextItem(
            id=f"item-{i}",
            content=(
                "Use PostgreSQL for database storage. "
                "Version must be >= 14. Set max_connections to 100. "
                "Enable true logging."
            ),
            kind="documentation",
            priority=5,
            recency=5,
            tokens=20,
        )
        for i in range(count)
    ]


async def mock_evaluator(packed: list[ContextItem]) -> float:
    """Scores based on ratio of non-adversarial items."""
    if not packed:
        return 0.0
    legitimate = [i for i in packed if not i.id.startswith("adversarial-")]
    return len(legitimate) / len(packed)


async def resilient_evaluator(_packed: list[ContextItem]) -> float:
    return 0.9


async def vulnerable_evaluator(packed: list[ContextItem]) -> float:
    has_adversarial = any(i.id.startswith("adversarial-") for i in packed)
    return 0.1 if has_adversarial else 0.9


DEFAULT_BUDGET = Budget(maxTokens=5000)


# ---------------------------------------------------------------------------
# Attack tests
# ---------------------------------------------------------------------------


class TestAttacks:
    @pytest.mark.parametrize("attack_type", ALL_ATTACK_TYPES)
    def test_produces_valid_context_items(self, attack_type):
        items = make_items(5)
        result = apply_attack(attack_type, items, 0.5, 42)

        assert isinstance(result, list)
        for item in result:
            assert hasattr(item, "id")
            assert hasattr(item, "content")
            assert isinstance(item.id, str)
            assert isinstance(item.content, str)

    @pytest.mark.parametrize("attack_type", ALL_ATTACK_TYPES)
    def test_respects_intensity_scaling(self, attack_type):
        items = make_items(5)
        low_result = apply_attack(attack_type, items, 0.2, 42)
        high_result = apply_attack(attack_type, items, 0.9, 42)
        low_injected = count_injected(items, low_result)
        high_injected = count_injected(items, high_result)

        assert high_injected >= low_injected

    @pytest.mark.parametrize("attack_type", ALL_ATTACK_TYPES)
    def test_deterministic_with_same_seed(self, attack_type):
        items = make_items(3)
        result1 = apply_attack(attack_type, items, 0.5, 99)
        result2 = apply_attack(attack_type, items, 0.5, 99)

        ids1 = [i.id for i in result1]
        ids2 = [i.id for i in result2]
        assert ids1 == ids2

        contents1 = [i.content for i in result1]
        contents2 = [i.content for i in result2]
        assert contents1 == contents2

    @pytest.mark.parametrize("attack_type", ALL_ATTACK_TYPES)
    def test_handles_empty_items(self, attack_type):
        result = apply_attack(attack_type, [], 0.5, 42)
        assert isinstance(result, list)

    @pytest.mark.parametrize("attack_type", ALL_ATTACK_TYPES)
    def test_handles_single_item(self, attack_type):
        items = [ContextItem(id="only", content="Single item.")]
        result = apply_attack(attack_type, items, 0.5, 42)
        assert len(result) >= 1

    def test_contradiction_injects_higher_priority(self):
        items = [ContextItem(id="doc", content="Use TypeScript.", priority=5)]
        result = apply_attack("contradiction", items, 1.0, 42)
        injected = [i for i in result if i.id.startswith("adversarial-")]

        assert len(injected) >= 1
        for item in injected:
            assert item.priority > 5

    def test_noise_flood_injects_documentation_kind(self):
        items = make_items(3)
        result = apply_attack("noise-flood", items, 0.5, 42)
        injected = [i for i in result if i.id.startswith("adversarial-noise-")]

        assert len(injected) >= 1
        for item in injected:
            assert item.kind == "documentation"
            assert item.priority >= 7

    def test_authority_spoof_injects_system_max_priority(self):
        items = make_items(3)
        result = apply_attack("authority-spoof", items, 0.5, 42)
        injected = [i for i in result if i.id.startswith("adversarial-authority-")]

        assert len(injected) >= 1
        for item in injected:
            assert item.priority == 10
            assert item.kind == "system"

    def test_temporal_poison_sets_supersedes(self):
        items = [ContextItem(id="guide-1", content="Always use ESLint.", priority=5, recency=5)]
        result = apply_attack("temporal-poison", items, 1.0, 42)
        new_items = [i for i in result if i.id.startswith("adversarial-temporal-new-")]

        assert len(new_items) >= 1
        for item in new_items:
            assert item.supersedes is not None
            assert item.recency == 10

    def test_relevance_dilution_injects_low_priority(self):
        items = make_items(3)
        result = apply_attack("relevance-dilution", items, 0.5, 42)
        injected = [i for i in result if i.id.startswith("adversarial-dilution-")]

        assert len(injected) >= 2
        for item in injected:
            assert item.priority <= 3

    def test_count_injected(self):
        items = make_items(3)
        result = apply_attack("noise-flood", items, 0.5, 42)
        count = count_injected(items, result)

        assert count == len(result) - len(items)
        assert count > 0

    @pytest.mark.parametrize("attack_type", ALL_ATTACK_TYPES)
    def test_describe_attack_returns_nonempty(self, attack_type):
        desc = describe_attack(attack_type)
        assert isinstance(desc, str)
        assert len(desc) > 10


# ---------------------------------------------------------------------------
# Tester tests
# ---------------------------------------------------------------------------


class TestAdversarialTester:
    @pytest.mark.asyncio
    async def test_full_probe_cycle(self):
        tester = create_adversarial_tester(
            AdversarialConfig(attacks=["contradiction", "noise-flood"], probe_rounds=1)
        )
        items = make_items(5)
        report = await tester.probe(items, DEFAULT_BUDGET, mock_evaluator)

        assert isinstance(report, ProbeReport)
        assert report.overall in ("resilient", "vulnerable", "critical")
        assert len(report.attacks) == 2
        assert report.total_probes > 0
        assert report.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_baseline_quality_is_correct(self):
        tester = create_adversarial_tester(
            AdversarialConfig(attacks=["contradiction"], probe_rounds=1)
        )
        items = make_items(3)
        report = await tester.probe(items, DEFAULT_BUDGET, mock_evaluator)

        assert report.baseline_quality == 1.0

    @pytest.mark.asyncio
    async def test_detects_quality_drop(self):
        tester = create_adversarial_tester(
            AdversarialConfig(attacks=["noise-flood"], probe_rounds=1)
        )
        items = make_items(3)
        report = await tester.probe(items, DEFAULT_BUDGET, mock_evaluator)

        assert report.attacks[0].quality_drop > 0
        assert report.attacks[0].injected_count > 0

    @pytest.mark.asyncio
    async def test_classifies_resilient(self):
        tester = create_adversarial_tester(
            AdversarialConfig(attacks=["contradiction"], probe_rounds=1)
        )
        items = make_items(3)
        report = await tester.probe(items, DEFAULT_BUDGET, resilient_evaluator)

        assert report.overall == "resilient"

    @pytest.mark.asyncio
    async def test_classifies_critical(self):
        tester = create_adversarial_tester(
            AdversarialConfig(attacks=["authority-spoof"], probe_rounds=1)
        )
        items = make_items(3)
        report = await tester.probe(items, DEFAULT_BUDGET, vulnerable_evaluator)

        assert report.attacks[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_identifies_worst_attack(self):
        tester = create_adversarial_tester(
            AdversarialConfig(
                attacks=["contradiction", "noise-flood", "authority-spoof"],
                probe_rounds=1,
            )
        )
        items = make_items(5)
        report = await tester.probe(items, DEFAULT_BUDGET, mock_evaluator)

        assert report.worst_attack is not None
        max_drop = max(a.quality_drop for a in report.attacks)
        assert report.worst_attack.quality_drop == max_drop

    @pytest.mark.asyncio
    async def test_empty_attacks_config(self):
        tester = create_adversarial_tester(AdversarialConfig(attacks=[], probe_rounds=1))
        items = make_items(3)
        report = await tester.probe(items, DEFAULT_BUDGET, mock_evaluator)

        assert len(report.attacks) == 0
        assert report.overall == "resilient"
        assert report.worst_attack is None

    @pytest.mark.asyncio
    async def test_empty_items(self):
        tester = create_adversarial_tester(
            AdversarialConfig(attacks=["contradiction"], probe_rounds=1)
        )
        report = await tester.probe([], DEFAULT_BUDGET, mock_evaluator)

        assert report.baseline_quality == 0.0

    @pytest.mark.asyncio
    async def test_custom_intensity(self):
        tester = create_adversarial_tester(
            AdversarialConfig(
                attacks=[AttackConfig(type="noise-flood", intensity=0.9)],
                probe_rounds=1,
            )
        )
        items = make_items(3)
        report = await tester.probe(items, DEFAULT_BUDGET, mock_evaluator)

        assert len(report.attacks) == 1
        assert report.attacks[0].attack == "noise-flood"

    @pytest.mark.asyncio
    async def test_probe_count(self):
        probe_rounds = 2
        attacks: list[str] = ["contradiction", "noise-flood", "subtle-error"]
        tester = create_adversarial_tester(
            AdversarialConfig(attacks=attacks, probe_rounds=probe_rounds)
        )
        items = make_items(3)
        report = await tester.probe(items, DEFAULT_BUDGET, mock_evaluator)

        expected = probe_rounds + len(attacks) * probe_rounds
        assert report.total_probes == expected
