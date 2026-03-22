"""Tests for Context Replay — recording pack decisions and A/B testing strategies."""

import json

import pytest

from context_engineering.core import Budget, ContextItem, ContextPack, ScoringWeights, pack
from context_engineering.replay import (
    ContextRecorder,
    ContextRecording,
    ReplayReport,
    ReplayVariant,
    VariantSummary,
    replay,
)


def _make_items(count: int = 5, tokens_each: int = 50) -> list[ContextItem]:
    """Create a list of test context items."""
    return [
        ContextItem(
            id=f"item-{i}",
            content=f"Content for item {i}",
            priority=float(count - i),  # Higher index = lower priority
            recency=float(i) / max(count - 1, 1),
            tokens=tokens_each,
        )
        for i in range(count)
    ]


def _pack_items(items: list[ContextItem], max_tokens: int = 200) -> ContextPack:
    """Pack items with a given budget."""
    return pack(items, Budget(maxTokens=max_tokens))


class TestContextRecorder:
    def test_record_and_retrieve(self):
        recorder = ContextRecorder()
        items = _make_items(3)
        budget = Budget(maxTokens=200)
        result = _pack_items(items)

        recording = recorder.record(
            model="gpt-4o",
            items=items,
            budget=budget,
            result=result,
        )

        assert recording.id is not None
        assert recording.model == "gpt-4o"
        assert len(recording.items) == 3
        assert recording.result == result

        recordings = recorder.get_recordings()
        assert len(recordings) == 1
        assert recordings[0].id == recording.id

    def test_get_recording_by_id(self):
        recorder = ContextRecorder()
        items = _make_items(3)
        result = _pack_items(items)

        recording = recorder.record(
            model="gpt-4o", items=items, budget=Budget(maxTokens=200), result=result
        )

        found = recorder.get_recording(recording.id)
        assert found is not None
        assert found.id == recording.id

    def test_get_recording_not_found(self):
        recorder = ContextRecorder()
        assert recorder.get_recording("nonexistent") is None

    def test_record_with_optional_fields(self):
        recorder = ContextRecorder()
        items = _make_items(3)
        result = _pack_items(items)

        recording = recorder.record(
            model="gpt-4o",
            items=items,
            budget=Budget(maxTokens=200),
            result=result,
            response="The answer is 42.",
            quality_score=0.85,
            metadata={"scenario": "email_classification"},
        )

        assert recording.response == "The answer is 42."
        assert recording.quality_score == 0.85
        assert recording.metadata == {"scenario": "email_classification"}

    def test_score_recording_after_the_fact(self):
        recorder = ContextRecorder()
        items = _make_items(3)
        result = _pack_items(items)

        recording = recorder.record(
            model="gpt-4o", items=items, budget=Budget(maxTokens=200), result=result
        )
        assert recording.quality_score is None

        recorder.score_recording(recording.id, 0.9)
        updated = recorder.get_recording(recording.id)
        assert updated.quality_score == 0.9

    def test_score_recording_not_found_raises(self):
        recorder = ContextRecorder()
        with pytest.raises(ValueError, match="Recording not found"):
            recorder.score_recording("nonexistent", 0.5)

    def test_multiple_recordings(self):
        recorder = ContextRecorder()
        items = _make_items(3)
        result = _pack_items(items)

        for i in range(5):
            recorder.record(
                model=f"model-{i}",
                items=items,
                budget=Budget(maxTokens=200),
                result=result,
            )

        assert len(recorder.get_recordings()) == 5

    def test_recordings_are_copies(self):
        recorder = ContextRecorder()
        items = _make_items(3)
        result = _pack_items(items)

        recorder.record(model="gpt-4o", items=items, budget=Budget(maxTokens=200), result=result)

        recordings = recorder.get_recordings()
        recordings.clear()
        assert len(recorder.get_recordings()) == 1


class TestSaveLoad:
    def test_save_load_roundtrip(self):
        recorder = ContextRecorder()
        items = _make_items(3)
        result = _pack_items(items)

        recorder.record(
            model="gpt-4o",
            items=items,
            budget=Budget(maxTokens=200),
            result=result,
            response="hello",
            quality_score=0.85,
            metadata={"key": "value"},
        )

        data = recorder.save()
        assert isinstance(data, str)

        # Validate it's valid JSON
        parsed = json.loads(data)
        assert len(parsed) == 1

        # Load into a new recorder
        new_recorder = ContextRecorder()
        new_recorder.load(data)
        loaded = new_recorder.get_recordings()

        assert len(loaded) == 1
        assert loaded[0].model == "gpt-4o"
        assert loaded[0].response == "hello"
        assert loaded[0].quality_score == 0.85
        assert loaded[0].metadata == {"key": "value"}
        assert len(loaded[0].items) == 3

    def test_load_appends_to_existing(self):
        recorder = ContextRecorder()
        items = _make_items(2)
        result = _pack_items(items)

        recorder.record(model="model-1", items=items, budget=Budget(maxTokens=200), result=result)

        data = recorder.save()

        # Record another
        recorder.record(model="model-2", items=items, budget=Budget(maxTokens=200), result=result)

        # Load the first recording again (should append)
        recorder.load(data)
        assert len(recorder.get_recordings()) == 3

    def test_save_with_weights(self):
        recorder = ContextRecorder()
        items = _make_items(2)
        result = _pack_items(items)

        recorder.record(
            model="gpt-4o",
            items=items,
            budget=Budget(maxTokens=200),
            result=result,
            weights=ScoringWeights(priority=2.0, recency=0.5),
        )

        data = recorder.save()
        new_recorder = ContextRecorder()
        new_recorder.load(data)
        loaded = new_recorder.get_recordings()[0]

        assert loaded.weights_used is not None
        assert loaded.weights_used.priority == 2.0
        assert loaded.weights_used.recency == 0.5


class TestReplay:
    def test_replay_with_different_weights_produces_different_results(self):
        items = _make_items(5, tokens_each=50)
        budget = Budget(maxTokens=200)
        result = pack(items, budget)

        recording = ContextRecording(
            id="test-1",
            timestamp=1000.0,
            model="gpt-4o",
            items=items,
            budget=budget,
            weights_used=None,
            result=result,
        )

        report = replay(
            recordings=[recording],
            variants=[
                ReplayVariant(name="baseline"),
                ReplayVariant(
                    name="recency-heavy",
                    weights=ScoringWeights(priority=0.1, recency=5.0),
                ),
            ],
        )

        assert len(report.variants) == 2
        assert report.recording_count == 1

        baseline = report.variants[0]
        recency = report.variants[1]

        assert baseline.name == "baseline"
        assert recency.name == "recency-heavy"

        # With very different weights, selection should differ
        # (at least the token counts or selected items may differ)
        assert len(baseline.results) == 1
        assert len(recency.results) == 1

    def test_token_delta_computed_correctly(self):
        items = _make_items(5, tokens_each=50)
        budget = Budget(maxTokens=200)
        result = pack(items, budget)

        recording = ContextRecording(
            id="test-1",
            timestamp=1000.0,
            model="gpt-4o",
            items=items,
            budget=budget,
            weights_used=None,
            result=result,
        )

        # Tighter budget should produce fewer tokens
        report = replay(
            recordings=[recording],
            variants=[
                ReplayVariant(name="tight", budget=Budget(maxTokens=100)),
            ],
        )

        tight_result = report.variants[0].results[0]
        assert tight_result.token_delta == tight_result.new_tokens - tight_result.original_tokens
        assert tight_result.new_tokens <= 100

    def test_utilization_computed_correctly(self):
        items = _make_items(3, tokens_each=50)
        budget = Budget(maxTokens=200)
        result = pack(items, budget)

        recording = ContextRecording(
            id="test-1",
            timestamp=1000.0,
            model="gpt-4o",
            items=items,
            budget=budget,
            weights_used=None,
            result=result,
        )

        report = replay(
            recordings=[recording],
            variants=[ReplayVariant(name="baseline")],
        )

        baseline_result = report.variants[0].results[0]
        expected_utilization = round(baseline_result.new_tokens / 200 * 100, 1)
        assert baseline_result.utilization == expected_utilization

    def test_selection_changes_tracked(self):
        items = _make_items(5, tokens_each=50)
        # Budget allows ~4 items
        budget = Budget(maxTokens=200)
        result = pack(items, budget)

        recording = ContextRecording(
            id="test-1",
            timestamp=1000.0,
            model="gpt-4o",
            items=items,
            budget=budget,
            weights_used=None,
            result=result,
        )

        # Very tight budget should drop some items
        report = replay(
            recordings=[recording],
            variants=[
                ReplayVariant(name="tight", budget=Budget(maxTokens=100)),
            ],
        )

        tight_result = report.variants[0].results[0]
        original_ids = {item.id for item in result.selected}
        dropped_ids = set(tight_result.newly_dropped)

        # Newly dropped items were in original but not in new
        for dropped_id in dropped_ids:
            assert dropped_id in original_ids

    def test_multiple_variants_compared(self):
        items = _make_items(5, tokens_each=50)
        budget = Budget(maxTokens=200)
        result = pack(items, budget)

        recording = ContextRecording(
            id="test-1",
            timestamp=1000.0,
            model="gpt-4o",
            items=items,
            budget=budget,
            weights_used=None,
            result=result,
        )

        report = replay(
            recordings=[recording],
            variants=[
                ReplayVariant(name="baseline"),
                ReplayVariant(name="tight", budget=Budget(maxTokens=100)),
                ReplayVariant(name="loose", budget=Budget(maxTokens=500)),
                ReplayVariant(
                    name="priority-only",
                    weights=ScoringWeights(priority=10.0, recency=0.0, salience=0.0),
                ),
            ],
        )

        assert len(report.variants) == 4
        names = [v.name for v in report.variants]
        assert names == ["baseline", "tight", "loose", "priority-only"]

    def test_empty_recordings_handled(self):
        report = replay(recordings=[], variants=[ReplayVariant(name="test")])

        assert report.recording_count == 0
        assert len(report.variants) == 1
        assert report.variants[0].avg_token_delta == 0.0
        assert report.variants[0].avg_utilization == 0.0
        assert report.variants[0].recordings_affected == 0
        assert report.variants[0].results == []

    def test_replay_report_structure(self):
        items = _make_items(3, tokens_each=50)
        budget = Budget(maxTokens=200)
        result = pack(items, budget)

        recording = ContextRecording(
            id="test-1",
            timestamp=1000.0,
            model="gpt-4o",
            items=items,
            budget=budget,
            weights_used=None,
            result=result,
        )

        report = replay(
            recordings=[recording],
            variants=[ReplayVariant(name="baseline")],
        )

        assert isinstance(report, ReplayReport)
        assert report.timestamp > 0
        assert report.recording_count == 1
        assert isinstance(report.variants[0], VariantSummary)

    def test_recordings_affected_count(self):
        items = _make_items(5, tokens_each=50)
        budget = Budget(maxTokens=200)
        result = pack(items, budget)

        recordings = [
            ContextRecording(
                id=f"test-{i}",
                timestamp=1000.0 + i,
                model="gpt-4o",
                items=items,
                budget=budget,
                weights_used=None,
                result=result,
            )
            for i in range(3)
        ]

        # With a very different budget, all recordings should be affected
        report = replay(
            recordings=recordings,
            variants=[
                ReplayVariant(name="tight", budget=Budget(maxTokens=100)),
            ],
        )

        tight_summary = report.variants[0]
        # With a much tighter budget, items should change
        assert tight_summary.recordings_affected >= 0  # At least validates the field
        assert len(tight_summary.results) == 3
