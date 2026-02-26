import asyncio
from context_engineering import PerplexitySegmenter, CerebrasProvider


class MockCerebrasProvider(CerebrasProvider):
    def __init__(self):
        pass

    def score_perplexity(self, text: str, model: str = "llama3.1-8b") -> float:
        base = 15.0
        if "quantum" in text.lower() or "entanglement" in text.lower():
            return 150.0
        return base + (len(text) % 5)


async def main():
    print("=== Perplexity-based Segmentation (Z-Score) Demo ===")

    mock_provider = MockCerebrasProvider()
    segmenter = PerplexitySegmenter(cerebras_provider=mock_provider, z_threshold=1.0)

    text = (
        "Python is a versatile programming language used for data science. "
        "It has a clean syntax and a massive ecosystem of libraries. "
        "Developers love Python for its readability and ease of use. "
        "Quantum entanglement is a physical phenomenon where particles share state. "
        "This happens regardless of the distance between the entangled particles. "
        "It is a core principle of quantum mechanics and computing."
    )

    print("\nSegmenting text with a 'surprise' topic shift (Python -> Quantum)...")
    segments = segmenter.segment(text, doc_id="tech_brief")

    print(f"Total segments detected: {len(segments)}")

    for seg in segments:
        print(f"\n--- {seg.id} ---")
        print(seg.to_context_text())


if __name__ == "__main__":
    asyncio.run(main())
