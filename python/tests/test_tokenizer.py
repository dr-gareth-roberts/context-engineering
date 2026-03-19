"""Tests for context_framework.tokenizer module."""

from __future__ import annotations

from context_framework.tokenizer import ApproxTokenCounter, TiktokenCounter


def test_approx_returns_zero_for_empty_string():
    counter = ApproxTokenCounter()
    assert counter.count("") == 0


def test_approx_returns_zero_for_whitespace_only():
    counter = ApproxTokenCounter()
    assert counter.count("   \t\n  ") == 0


def test_approx_returns_positive_for_hello_world():
    counter = ApproxTokenCounter()
    result = counter.count("hello world")
    assert result > 0


def test_approx_uses_configured_chars_per_token():
    # With 1 char per token, "abcde" (5 chars) should yield 5 tokens
    counter = ApproxTokenCounter(chars_per_token=1.0)
    assert counter.count("abcde") == 5

    # With 5 chars per token, "abcde" (5 chars) should yield 1 token
    counter2 = ApproxTokenCounter(chars_per_token=5.0)
    assert counter2.count("abcde") == 1


def test_tiktoken_returns_zero_for_empty_string():
    counter = TiktokenCounter()
    assert counter.count("") == 0


def test_tiktoken_returns_zero_for_whitespace_only():
    counter = TiktokenCounter()
    assert counter.count("   \t\n  ") == 0


def test_tiktoken_returns_positive_for_hello_world():
    counter = TiktokenCounter()
    result = counter.count("hello world")
    assert result > 0
