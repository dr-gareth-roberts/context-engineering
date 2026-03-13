import asyncio
from typing import List

from context_engineering import EmbeddingProvider, EmbeddingResult, SemanticSegmenter


class MockEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: List[str], model: str) -> EmbeddingResult:
        vectors = []
        for text in texts:
            # High separation between AI and Cooking
            if any(
                word in text.lower() for word in ["machine", "learning", "neural", "data", "ai"]
            ):
                vectors.append([1.0, 0.0, 0.0])
            elif any(word in text.lower() for word in ["cook", "steak", "salt", "oil", "pan"]):
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.5, 0.5, 0.0])
        return EmbeddingResult(vectors=vectors, model="mock")


async def main():
    print("=== Semantic Segmentation (Autocorrelation) Demo ===")

    mock_provider = MockEmbeddingProvider()
    # Using window_size=1 and 0 threshold to ensure any dip triggers
    # and lowering max_tokens to allow small segments
    segmenter = SemanticSegmenter(embedding_provider=mock_provider, window_size=1, threshold=0.3)

    mixed_text = (
        "Machine learning is a field of artificial intelligence. "
        "It uses neural networks to process large amounts of data. "
        "Deep learning is a subset of machine learning. "
        "To cook a perfect steak, you need high heat and a cast iron pan. "
        "Season the meat generously with salt and pepper before cooking. "
        "Heat the oil until it starts to shimmer in the pan."
    )

    print("\nSegmenting text with abrupt topic shifts...")
    segments = segmenter.segment(mixed_text, doc_id="mixed_doc")

    print(f"Total segments detected: {len(segments)}")

    for seg in segments:
        print(f"\n--- {seg.id} ---")
        print(seg.to_context_text())


if __name__ == "__main__":
    asyncio.run(main())
