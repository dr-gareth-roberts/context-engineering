import asyncio
from typing import List
from context_engineering import (
    HybridSegmenter, 
    EmbeddingResult, 
    EmbeddingProvider, 
    CerebrasProvider
)

class MockEmbeddings(EmbeddingProvider):
    def embed(self, texts: List[str], model: str) -> EmbeddingResult:
        vectors = []
        for text in texts:
            if "ai" in text.lower() or "machine" in text.lower():
                vectors.append([1.0, 0.0, 0.0])
            elif "steak" in text.lower() or "chef" in text.lower():
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return EmbeddingResult(vectors=vectors, model="mock")

class MockCerebras(CerebrasProvider):
    def __init__(self): pass
    def score_perplexity(self, text: str, model: str = "llama3.1-8b") -> float:
        if "quantum" in text.lower(): return 200.0
        return 10.0

async def main():
    print("=== Hybrid Segmentation Demo ===")
    
    embed_prov = MockEmbeddings()
    cerebras_prov = MockCerebras()
    
    segmenter = HybridSegmenter(
        embedding_provider=embed_prov,
        cerebras_provider=cerebras_prov,
        max_tokens=100,
        semantic_threshold=0.5
    )
    
    text = """# Section 1: AI
Artificial intelligence is changing the world. Machine learning models are becoming more powerful.

# Section 2: Culinary Arts
Cooking a perfect steak requires a hot pan. The chef seasons the meat with salt.

# Section 3: Physics
Quantum entanglement is very confusing. It involves particles sharing state across distance.
"""

    print("\nSegmenting complex document with structural, semantic, and perplexity shifts...")
    segments = segmenter.segment(text, doc_id="hybrid_doc")
    
    print(f"Total segments: {len(segments)}")
    
    for seg in segments:
        print(f"\n--- {seg.id} ---")
        print(seg.to_context_text())

if __name__ == "__main__":
    asyncio.run(main())
