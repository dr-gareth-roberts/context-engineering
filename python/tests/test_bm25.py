"""Tests for BM25 index and Unicode tokenizer."""

from __future__ import annotations

from context_engineering.bm25 import create_bm25_index, unicode_tokenize


class TestUnicodeTokenize:
    def test_ascii_text(self):
        assert unicode_tokenize("Hello World") == ["hello", "world"]

    def test_filters_short_tokens(self):
        assert unicode_tokenize("I am a dog") == ["am", "dog"]

    def test_unicode_characters(self):
        tokens = unicode_tokenize("café résumé naïve")
        assert "café" in tokens
        assert "résumé" in tokens
        assert "naïve" in tokens

    def test_cjk_characters(self):
        tokens = unicode_tokenize("hello 世界")
        assert "hello" in tokens
        assert "世界" in tokens
        assert len(tokens) == 2

    def test_empty_string(self):
        assert unicode_tokenize("") == []

    def test_none_input(self):
        assert unicode_tokenize(None) == []

    def test_mixed_alphanumeric(self):
        tokens = unicode_tokenize("node16 react19 ts5")
        assert "node16" in tokens
        assert "react19" in tokens
        assert "ts5" in tokens


class TestBM25Index:
    def test_matching_scores_higher(self):
        idx = create_bm25_index()
        idx.add("doc1", "context engineering for language models")
        idx.add("doc2", "cooking recipes for pasta dishes")
        s1 = idx.score("context engineering", "doc1")
        s2 = idx.score("context engineering", "doc2")
        assert s1 > s2
        assert s2 == 0

    def test_score_all(self):
        idx = create_bm25_index()
        idx.add("a", "token budget packing")
        idx.add("b", "token estimation heuristic")
        idx.add("c", "unrelated content about weather")
        scores = idx.score_all("token budget")
        assert scores["a"] > 0
        assert scores["b"] > 0
        assert scores["c"] == 0
        assert scores["a"] > scores["b"]

    def test_empty_index(self):
        idx = create_bm25_index()
        assert idx.score("anything", "nonexistent") == 0

    def test_empty_query(self):
        idx = create_bm25_index()
        idx.add("doc1", "some content")
        assert idx.score("", "doc1") == 0

    def test_document_count(self):
        idx = create_bm25_index()
        assert idx.document_count == 0
        idx.add("a", "one")
        idx.add("b", "two")
        assert idx.document_count == 2

    def test_custom_parameters(self):
        idx = create_bm25_index(k1=2.0, b=0.5)
        idx.add("doc1", "test test test")
        assert idx.score("test", "doc1") > 0

    def test_custom_tokenizer(self):
        idx = create_bm25_index(tokenizer=lambda text: [s.strip().lower() for s in text.split(",")])
        idx.add("doc1", "alpha, beta, gamma")
        assert idx.score("alpha", "doc1") > 0

    def test_idf_rare_terms_score_higher(self):
        idx = create_bm25_index()
        idx.add("d1", "the common word appears here")
        idx.add("d2", "the common word too")
        idx.add("d3", "rare unique specialized term")
        rare_score = idx.score("rare", "d3")
        common_score = idx.score("common", "d1")
        assert rare_score > common_score

    def test_readd_same_id_does_not_leak_corpus_stats(self):
        """Re-adding the same id must refresh, not accumulate, corpus stats.

        Regression: add() previously never subtracted the prior document's
        length/df, so re-adding an id inflated _total_length and _df while
        document_count stayed flat, distorting avgdl and idf for every doc.
        """
        idx = create_bm25_index()
        idx.add("doc1", "context engineering token budget")

        count_after_first = idx.document_count
        total_after_first = idx._total_length
        df_after_first = dict(idx._df)
        score_after_first = idx.score("context budget", "doc1")

        # Re-add the exact same content under the same id (incremental refresh).
        idx.add("doc1", "context engineering token budget")

        assert idx.document_count == count_after_first
        assert idx._total_length == total_after_first
        assert dict(idx._df) == df_after_first
        assert idx.score("context budget", "doc1") == score_after_first

    def test_readd_with_new_content_replaces_old_contribution(self):
        """Re-adding an id with different content reflects only the new text."""
        idx = create_bm25_index()
        idx.add("doc1", "alpha beta gamma")
        idx.add("doc1", "delta epsilon")

        assert idx.document_count == 1
        assert idx._total_length == 2
        # Old terms must be gone from the document frequency table.
        assert "alpha" not in idx._df
        assert "beta" not in idx._df
        assert "gamma" not in idx._df
        # New terms must be present exactly once.
        assert idx._df["delta"] == 1
        assert idx._df["epsilon"] == 1
        # Querying an old term yields no score; a new term scores.
        assert idx.score("alpha", "doc1") == 0
        assert idx.score("delta", "doc1") > 0
