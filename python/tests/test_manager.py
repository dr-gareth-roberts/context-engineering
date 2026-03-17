from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from context_framework import ContextKind, ContextManager, RollingSummaryConfig


def sized_text(tokens: int, label: str = "x") -> str:
    return (label * 4 * tokens)[: 4 * tokens]


class ContextManagerTests(unittest.TestCase):
    def test_context_respects_effective_budget(self) -> None:
        manager = ContextManager(default_token_budget=120, reserved_response_tokens=20)
        manager.add_system(sized_text(10), source="core-policy")

        for idx in range(8):
            manager.add_document(
                f"doc-{idx} " + sized_text(20, label=str(idx)),
                source=f"doc-{idx}",
                importance=0.2,
            )

        packet = manager.build_context("doc")
        self.assertLessEqual(packet.used_tokens, 100)
        self.assertEqual(packet.token_budget, 100)

    def test_pinned_memory_is_prioritized(self) -> None:
        manager = ContextManager(default_token_budget=70, reserved_response_tokens=20)
        manager.add_memory(
            "Critical preference: always answer with bullet points.",
            source="pinned-memory",
            pinned=True,
            importance=0.1,
        )
        manager.add_memory(
            "Optional preference: include architecture history details.",
            source="normal-memory",
            pinned=False,
            importance=1.0,
        )
        manager.add_document(
            sized_text(20, "d"),
            source="doc-noise",
            importance=1.0,
        )

        packet = manager.build_context("architecture details")
        selected_sources = {item.source for item in packet.items}
        self.assertIn("pinned-memory", selected_sources)

    def test_query_relevance_prefers_matching_document(self) -> None:
        manager = ContextManager(default_token_budget=56, reserved_response_tokens=20)
        manager.add_document(
            "Billing invoices and annual plan payment schedule documentation. "
            + sized_text(18, "b"),
            source="billing-doc",
            importance=0.5,
        )
        manager.add_document(
            "Retry policy for failed jobs with exponential backoff and limits. "
            + sized_text(18, "r"),
            source="retry-doc",
            importance=0.5,
        )

        packet = manager.build_context("How do retries for failed jobs work?")
        selected_sources = [
            item.source for item in packet.items if item.kind == ContextKind.DOCUMENT
        ]
        self.assertIn("retry-doc", selected_sources)
        self.assertNotIn("billing-doc", selected_sources)

    def test_recent_conversation_is_preserved_first(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        manager = ContextManager(default_token_budget=30, reserved_response_tokens=10)
        manager.add_message("user", sized_text(10, "a"), created_at=base + timedelta(minutes=1))
        manager.add_message(
            "assistant", sized_text(10, "b"), created_at=base + timedelta(minutes=2)
        )
        manager.add_message("user", sized_text(10, "c"), created_at=base + timedelta(minutes=3))
        manager.add_message(
            "assistant", sized_text(10, "d"), created_at=base + timedelta(minutes=4)
        )

        packet = manager.build_context("latest answer")
        conversation_text = [item.text for item in packet.items if item.kind == ContextKind.MESSAGE]
        self.assertEqual(conversation_text, [sized_text(10, "c"), sized_text(10, "d")])

    def test_rolling_summary_prunes_old_conversation(self) -> None:
        manager = ContextManager(
            default_token_budget=140,
            reserved_response_tokens=20,
            rolling_summary=RollingSummaryConfig(
                enabled=True,
                trigger_messages=4,
                keep_recent_messages=2,
                target_tokens=300,
            ),
        )

        for idx in range(8):
            role = "user" if idx % 2 == 0 else "assistant"
            manager.add_message(role, f"turn {idx}: " + sized_text(6, str(idx)))

        all_items = manager.all_items()
        summary_items = [
            item
            for item in all_items
            if item.kind == ContextKind.SUMMARY and item.source == "rolling-conversation"
        ]
        conversation_items = [item for item in all_items if item.kind == ContextKind.MESSAGE]

        self.assertEqual(len(summary_items), 1)
        self.assertEqual(len(conversation_items), 2)
        self.assertIn("turn 0", summary_items[0].text)
        self.assertIn("turn 5", summary_items[0].text)

        packet = manager.build_context("turn")
        summary_sources = [item.source for item in packet.items if item.kind == ContextKind.SUMMARY]
        self.assertIn("rolling-conversation", summary_sources)

    def test_build_messages_abstains_when_only_system_context_is_high_confidence(self) -> None:
        manager = ContextManager(default_token_budget=60, reserved_response_tokens=10)
        manager.add_system("Follow policy exactly.", source="policy", importance=1.0)
        manager.add_document("Weak evidence.", source="doc", importance=0.2)

        messages = manager.build_messages(
            "What happened?",
            abstain_on_low_confidence=True,
            min_confidence_threshold=0.5,
        )

        self.assertEqual(
            messages,
            [{"role": "system", "content": "I abstain: insufficient evidence to answer."}],
        )

    def test_build_messages_abstains_without_evidence(self) -> None:
        manager = ContextManager(default_token_budget=80, reserved_response_tokens=20)
        manager.add_system("You are a precise assistant.", source="policy", importance=1.0)

        messages = manager.build_messages(
            "What happened?",
            abstain_on_low_confidence=True,
            min_confidence_threshold=0.4,
        )

        self.assertEqual(
            messages,
            [{"role": "system", "content": "I abstain: insufficient evidence to answer."}],
        )

    def test_build_messages_uses_evidence_confidence(self) -> None:
        manager = ContextManager(default_token_budget=80, reserved_response_tokens=20)
        manager.add_system("You are a precise assistant.", source="policy", importance=1.0)
        manager.add_document("Incident timeline", source="timeline", importance=0.8)

        messages = manager.build_messages(
            "What happened?",
            abstain_on_low_confidence=True,
            min_confidence_threshold=0.4,
        )

        self.assertNotEqual(
            messages,
            [{"role": "system", "content": "I abstain: insufficient evidence to answer."}],
        )


if __name__ == "__main__":
    unittest.main()
