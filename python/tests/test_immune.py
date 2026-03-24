"""Tests for the context immune system module."""

from __future__ import annotations

from context_engineering.core import Budget, ContextItem
from context_engineering.immune import (
    FailureRecord,
    Fingerprint,
    ImmuneSystemConfig,
    ScreeningResult,
    Stats,
    compare_fingerprints,
    compute_stats,
    create_antibody,
    create_immune_system,
    extract_fingerprint,
    match_antibody,
    reset_id_counter,
)


def _make_item(id: str, content: str, **kwargs) -> ContextItem:
    tokens = kwargs.pop("tokens", max(1, int(len(content.split()) * 1.3)))
    return ContextItem(id=id, content=content, tokens=tokens, **kwargs)


DEFAULT_BUDGET = Budget(maxTokens=4000)


def _toxic_items() -> list[ContextItem]:
    return [
        _make_item("sys", "you are a helpful assistant", kind="system", priority=1.0, recency=1.0),
        _make_item(
            "stale1", "old data from archives one", kind="retrieval", priority=0.2, recency=0.05
        ),
        _make_item(
            "stale2", "old data from archives two", kind="retrieval", priority=0.15, recency=0.08
        ),
        _make_item(
            "stale3", "old data from archives three", kind="retrieval", priority=0.1, recency=0.03
        ),
    ]


def _safe_items() -> list[ContextItem]:
    return [
        _make_item("sys", "you are a helpful assistant", kind="system", priority=1.0, recency=1.0),
        _make_item(
            "fresh1",
            "brand new recent information about technology",
            kind="conversation",
            priority=0.8,
            recency=0.95,
        ),
        _make_item(
            "fresh2",
            "another piece of recent relevant data",
            kind="conversation",
            priority=0.7,
            recency=0.9,
        ),
    ]


def _make_failure(**overrides) -> FailureRecord:
    defaults = dict(
        items=_toxic_items(),
        budget=DEFAULT_BUDGET,
        symptom="Model hallucinated outdated facts",
        diagnosis="Context dominated by stale retrieval items",
    )
    defaults.update(overrides)
    return FailureRecord(**defaults)


# -- compute_stats -----------------------------------------------------------


class TestComputeStats:
    def test_empty_list(self):
        stats = compute_stats([])
        assert stats.min == 0.0
        assert stats.max == 0.0
        assert stats.mean == 0.0
        assert stats.std == 0.0

    def test_single_value(self):
        stats = compute_stats([5.0])
        assert stats.min == 5.0
        assert stats.max == 5.0
        assert stats.mean == 5.0
        assert stats.std == 0.0

    def test_identical_values(self):
        stats = compute_stats([3.0, 3.0, 3.0])
        assert stats.std == 0.0
        assert stats.mean == 3.0


# -- extract_fingerprint -----------------------------------------------------


class TestExtractFingerprint:
    def test_empty_items(self):
        fp = extract_fingerprint([])
        assert fp.item_count == 0
        assert fp.kinds_present == []
        assert fp.staleness_ratio == 0.0

    def test_extracts_kinds(self):
        items = [
            _make_item("1", "hello", kind="system"),
            _make_item("2", "world", kind="retrieval"),
            _make_item("3", "foo", kind="system"),
        ]
        fp = extract_fingerprint(items)
        assert "system" in fp.kinds_present
        assert "retrieval" in fp.kinds_present
        assert abs(fp.kind_ratios["system"] - 2 / 3) < 0.01

    def test_staleness_ratio(self):
        items = [
            _make_item("1", "a", recency=0.1),
            _make_item("2", "b", recency=0.15),
            _make_item("3", "c", recency=0.5),
            _make_item("4", "d", recency=0.9),
        ]
        fp = extract_fingerprint(items)
        assert fp.staleness_ratio == 0.5

    def test_redundancy_detection(self):
        content = "the quick brown fox jumps over the lazy dog"
        items = [
            _make_item("1", content),
            _make_item("2", content),
            _make_item("3", "completely different unique text here"),
        ]
        fp = extract_fingerprint(items)
        assert fp.redundancy_estimate > 0

    def test_no_redundancy_for_distinct_items(self):
        items = [
            _make_item("1", "alpha beta gamma delta epsilon"),
            _make_item("2", "zeta eta theta iota kappa lambda"),
        ]
        fp = extract_fingerprint(items)
        assert fp.redundancy_estimate == 0.0


# -- compare_fingerprints ----------------------------------------------------


class TestCompareFingerprints:
    def test_identical_score_one(self):
        fp = Fingerprint(
            kinds_present=["system"],
            kind_ratios={"system": 1.0},
            priority_stats=Stats(min=0.5, max=0.5, mean=0.5, std=0.0),
            recency_stats=Stats(min=0.5, max=0.5, mean=0.5, std=0.0),
            token_utilization=0.8,
            item_count=5,
            staleness_ratio=0.2,
            redundancy_estimate=0.1,
        )
        assert abs(compare_fingerprints(fp, fp) - 1.0) < 0.01

    def test_very_different_score_low(self):
        fp_a = Fingerprint(
            kinds_present=["system"],
            kind_ratios={"system": 1.0},
            priority_stats=Stats(min=0.9, max=1.0, mean=0.95, std=0.02),
            recency_stats=Stats(min=0.9, max=1.0, mean=0.95, std=0.02),
            token_utilization=0.95,
            item_count=20,
            staleness_ratio=0.0,
            redundancy_estimate=0.0,
        )
        fp_b = Fingerprint(
            kinds_present=["retrieval"],
            kind_ratios={"retrieval": 1.0},
            priority_stats=Stats(min=0.0, max=0.1, mean=0.05, std=0.02),
            recency_stats=Stats(min=0.0, max=0.1, mean=0.05, std=0.02),
            token_utilization=0.1,
            item_count=2,
            staleness_ratio=1.0,
            redundancy_estimate=0.9,
        )
        assert compare_fingerprints(fp_a, fp_b) < 0.5

    def test_symmetry(self):
        fp_a = Fingerprint(
            kinds_present=["system", "code"],
            kind_ratios={"system": 0.6, "code": 0.4},
            priority_stats=Stats(min=0.3, max=0.9, mean=0.6, std=0.2),
            recency_stats=Stats(min=0.4, max=0.8, mean=0.6, std=0.15),
            token_utilization=0.7,
            item_count=10,
            staleness_ratio=0.1,
            redundancy_estimate=0.05,
        )
        fp_b = Fingerprint(
            kinds_present=["system", "retrieval"],
            kind_ratios={"system": 0.5, "retrieval": 0.5},
            priority_stats=Stats(min=0.2, max=0.8, mean=0.5, std=0.25),
            recency_stats=Stats(min=0.3, max=0.7, mean=0.5, std=0.2),
            token_utilization=0.6,
            item_count=8,
            staleness_ratio=0.2,
            redundancy_estimate=0.15,
        )
        assert abs(compare_fingerprints(fp_a, fp_b) - compare_fingerprints(fp_b, fp_a)) < 1e-10


# -- create_antibody / match_antibody ----------------------------------------


class TestAntibodies:
    def setup_method(self):
        reset_id_counter()

    def test_create_antibody_fields(self):
        record = _make_failure()
        ab = create_antibody(record)
        assert ab.id == "ab-1"
        assert ab.symptom == "Model hallucinated outdated facts"
        assert ab.severity == "warning"
        assert ab.match_threshold == 0.7
        assert ab.pattern.item_count == 4

    def test_match_identical(self):
        record = _make_failure()
        ab = create_antibody(record)
        fp = extract_fingerprint(record.items, record.budget)
        result = match_antibody(ab, fp)
        assert result["matches"] is True
        assert abs(result["similarity"] - 1.0) < 0.01

    def test_no_match_different(self):
        record = _make_failure()
        ab = create_antibody(record)
        different = [
            _make_item(
                "x",
                "completely unique new content",
                kind="conversation",
                priority=0.9,
                recency=0.95,
            ),
        ]
        fp = extract_fingerprint(different, Budget(maxTokens=100))
        result = match_antibody(ab, fp)
        assert result["matches"] is False


# -- ImmuneSystem -------------------------------------------------------------


class TestImmuneSystem:
    def setup_method(self):
        reset_id_counter()

    def test_starts_empty(self):
        immune = create_immune_system()
        assert immune.get_antibodies() == []

    def test_record_failure(self):
        immune = create_immune_system()
        ab = immune.record_failure(_make_failure())
        assert ab.id == "ab-1"
        assert len(immune.get_antibodies()) == 1

    def test_screen_fires_on_similar(self):
        immune = create_immune_system()
        immune.record_failure(_make_failure())
        result = immune.screen(_toxic_items(), DEFAULT_BUDGET)
        assert len(result.antibodies_fired) == 1

    def test_screen_safe_for_different(self):
        immune = create_immune_system()
        immune.record_failure(_make_failure())
        result = immune.screen(_safe_items(), DEFAULT_BUDGET)
        assert result.safe is True

    def test_screen_safe_with_no_antibodies(self):
        immune = create_immune_system()
        result = immune.screen(_toxic_items(), DEFAULT_BUDGET)
        assert result.safe is True
        assert result.antibodies_fired == []

    def test_block_severity_unsafe(self):
        immune = create_immune_system()
        immune.record_failure(_make_failure(severity="block"))
        result = immune.screen(_toxic_items(), DEFAULT_BUDGET)
        if result.antibodies_fired:
            assert result.safe is False
            assert len(result.blocked) == 1

    def test_remove_antibody(self):
        immune = create_immune_system()
        ab = immune.record_failure(_make_failure())
        assert immune.remove_antibody(ab.id) is True
        assert len(immune.get_antibodies()) == 0

    def test_remove_antibody_unknown_id(self):
        immune = create_immune_system()
        assert immune.remove_antibody("nonexistent") is False

    def test_reset(self):
        immune = create_immune_system()
        immune.record_failure(_make_failure())
        immune.reset()
        assert len(immune.get_antibodies()) == 0

    def test_max_antibodies_pruning(self):
        immune = create_immune_system(ImmuneSystemConfig(max_antibodies=3))
        for i in range(5):
            immune.record_failure(_make_failure(symptom=f"failure-{i}"))
        assert len(immune.get_antibodies()) == 3

    def test_export_import_roundtrip(self):
        immune = create_immune_system()
        immune.record_failure(_make_failure(symptom="test"))
        state = immune.export_state()
        assert len(state.antibodies) == 1

        immune2 = create_immune_system()
        immune2.import_state(state)
        assert len(immune2.get_antibodies()) == 1

    def test_on_alert_callback(self):
        calls: list[ScreeningResult] = []
        cfg = ImmuneSystemConfig(on_alert=lambda r: calls.append(r))
        immune = create_immune_system(cfg)
        immune.record_failure(_make_failure())
        immune.screen(_toxic_items(), DEFAULT_BUDGET)
        assert len(calls) > 0

    def test_on_alert_not_called_when_clean(self):
        calls: list[ScreeningResult] = []
        cfg = ImmuneSystemConfig(on_alert=lambda r: calls.append(r))
        immune = create_immune_system(cfg)
        immune.screen(_safe_items(), DEFAULT_BUDGET)
        assert len(calls) == 0

    def test_screen_empty_items(self):
        immune = create_immune_system()
        immune.record_failure(_make_failure())
        result = immune.screen([], DEFAULT_BUDGET)
        assert result.safe is True
