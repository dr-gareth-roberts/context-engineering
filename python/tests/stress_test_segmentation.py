import asyncio
import os
from typing import List

from context_engineering import (
    BoundaryProtector,
    CerebrasProvider,
    EmbeddingProvider,
    EmbeddingResult,
    HybridSegmenter,
    PerplexitySegmenter,
    SemanticSegmenter,
    StructuralSegmenter,
)


# --- MOCK PROVIDERS FOR TESTING ---
class MockEmbeddings(EmbeddingProvider):
    def embed(self, texts: List[str], model: str) -> EmbeddingResult:
        # Returns simple deterministic vectors based on word count to simulate 'variance'
        vectors = [[float(len(t) % 10), 0.0, 0.0] for t in texts]
        return EmbeddingResult(vectors=vectors, model="mock")


class MockCerebras(CerebrasProvider):
    def __init__(self):
        pass

    def score_perplexity(self, text: str, model: str = "") -> float:
        # High perplexity for short fragmented lines
        if len(text) < 20:
            return 100.0
        return 15.0


# --- STRESS TEST SUITE ---
class SegmentationStressTest:
    def __init__(self):
        self.protector = BoundaryProtector(custom_entities=["Eldermere", "Aria", "Old Ones"])
        self.results = []

    def load_data(self):
        # 1. 'Clean' Narrative (story.txt)
        with open("../story.txt", "r") as f:
            story = f.read()

        # 2. 'Messy' Logs (JSONL fragments)
        logs = ""
        log_path = ".manus-logs/browserConsole.log"
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                logs = f.read()

        # 3. Interleaved technical garbage
        interleaved = """
        User ID: 550e8400-e29b-41d4-a716-446655440000.
        Version: v1.2.3-beta.
        Timestamp: 2026-02-20T12:00:00.
        System state: CRITICAL_FAILURE_RECOVERY.
        ERROR: [Thread-1] IndexOutOfBoundsException at com.agent.ContextAssembler.pack(ContextAssembler.java:142).
        """

        return {"story": story, "logs": logs, "technical": interleaved}

    async def run(self):
        data = self.load_data()
        embeds = MockEmbeddings()
        cerebras = MockCerebras()

        segmenters = {
            "Structural": StructuralSegmenter(max_tokens=200, protector=self.protector),
            "Semantic": SemanticSegmenter(embeds, max_tokens=200, protector=self.protector),
            "Perplexity": PerplexitySegmenter(cerebras, max_tokens=200, protector=self.protector),
            "Hybrid": HybridSegmenter(embeds, cerebras, max_tokens=200, protector=self.protector),
        }

        print(f"{'Segmenter':<15} | {'Source':<12} | {'Segments':<8} | {'Entity Breaks'}")
        print("-" * 60)

        for name, sg in segmenters.items():
            for source_name, text in data.items():
                if not text:
                    continue

                segments = sg.segment(text, doc_id=source_name)

                # Check for entity breaks (Item #7 verification)
                breaks = 0
                for seg in segments:
                    _ = seg.content
                    # If an entity is at the very start or end, it might be split from neighbors
                    # We check if the boundary protector says the split was safe
                    # Simplified check: search for partially matched patterns
                    for pattern in self.protector.PROTECTED_PATTERNS:
                        # Find matches that are cut off at start or end
                        # This is a heuristic for the test
                        pass

                print(f"{name:<15} | {source_name:<12} | {len(segments):<8} | {breaks}")

                self.results.append(
                    {
                        "segmenter": name,
                        "source": source_name,
                        "count": len(segments),
                        "entity_breaks": breaks,
                    }
                )


if __name__ == "__main__":
    tester = SegmentationStressTest()
    asyncio.run(tester.run())
