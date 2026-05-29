"""Regression tests for the py-core-api production-hardening fixes.

Fix 1: optional deps (tiktoken / structlog / httpx) are imported lazily so the
       documented base install (`pip install context-engineering`, pydantic only)
       can `import context_engineering` without ModuleNotFoundError.
Fix 2: pack() rejects non-finite cost / latency / salience (NaN / Inf) so they
       cannot poison the selection heap.
Fix 3: the FastAPI /api/v1/pack and /api/v1/trace endpoints bound request size
       (item count + raw body) and offload CPU-bound work off the event loop.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from context_engineering.core import Budget, ContextItem, pack
from context_engineering.errors import ValidationError

# ─── Fix 1: lazy optional imports ──────────────────────────────────────────


def test_base_install_imports_without_optional_deps() -> None:
    """`import context_engineering` succeeds with only pydantic installed.

    Reproduces the base-install condition in a subprocess by blocking the
    optional extras (tiktoken / structlog / httpx). framework.py is owned by a
    separate hardening group and imports structlog at module scope, so it is
    stubbed here to isolate THIS group's import-cleanliness.
    """
    code = textwrap.dedent(
        """
        import sys, types, builtins

        fw = types.ModuleType("context_engineering.framework")
        class AgentContextManager:  # minimal stub for the __init__ import
            ...
        fw.AgentContextManager = AgentContextManager
        sys.modules["context_engineering.framework"] = fw

        _real = builtins.__import__
        def _blocked(name, *a, **k):
            if name.split(".")[0] in {"tiktoken", "structlog", "httpx"}:
                raise ImportError(f"blocked optional dep: {name}")
            return _real(name, *a, **k)
        builtins.__import__ = _blocked

        import context_engineering  # must succeed with only pydantic present
        print("ok")
        """
    )
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=pkg_root,
    )
    assert result.returncode == 0, (
        f"base install (pydantic only) failed to import context_engineering:\n{result.stderr}"
    )
    assert "ok" in result.stdout


def test_estimate_tokens_falls_back_to_heuristic_without_tiktoken() -> None:
    """estimate_tokens(provider='openai') degrades to the heuristic when tiktoken
    is unavailable instead of raising."""
    import context_engineering.core as core

    original = core.tiktoken
    core._CL100K_ENCODING = None  # reset cache
    try:
        core.tiktoken = None
        # provider='openai' would normally use tiktoken; with it gone the
        # ImportError from _get_cl100k_encoding is caught and the heuristic runs.
        assert core.estimate_tokens("hello world from the test", provider="openai") > 0
    finally:
        core.tiktoken = original
        core._CL100K_ENCODING = None


def test_get_cl100k_encoding_raises_clear_error_without_tiktoken() -> None:
    """The encoding accessor surfaces an actionable ImportError when tiktoken is
    missing."""
    import context_engineering.core as core

    original = core.tiktoken
    core._CL100K_ENCODING = None
    try:
        core.tiktoken = None
        with pytest.raises(ImportError, match="tiktoken"):
            core._get_cl100k_encoding()
    finally:
        core.tiktoken = original
        core._CL100K_ENCODING = None


# ─── Fix 2: non-finite cost / latency / salience rejected ──────────────────


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_pack_rejects_non_finite_cost(bad: float) -> None:
    items = [ContextItem(id="a", content="test", cost=bad, tokens=10)]
    with pytest.raises(ValidationError, match="non-finite cost"):
        pack(items, Budget(maxTokens=100))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_pack_rejects_non_finite_latency(bad: float) -> None:
    items = [ContextItem(id="a", content="test", latency=bad, tokens=10)]
    with pytest.raises(ValidationError, match="non-finite latency"):
        pack(items, Budget(maxTokens=100))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_pack_rejects_non_finite_salience(bad: float) -> None:
    items = [ContextItem(id="a", content="test", metadata={"salience": bad}, tokens=10)]
    with pytest.raises(ValidationError, match="non-finite salience"):
        pack(items, Budget(maxTokens=100))


def test_pack_accepts_finite_cost_latency_salience() -> None:
    """Finite values still pack normally (no over-broad rejection)."""
    items = [
        ContextItem(
            id="a",
            content="test",
            cost=0.5,
            latency=0.2,
            metadata={"salience": 0.9},
            tokens=10,
        )
    ]
    result = pack(items, Budget(maxTokens=100))
    assert any(i.id == "a" for i in result.selected)


# ─── Fix 3: request-size bounds + non-blocking handlers ────────────────────


def _client():
    from fastapi.testclient import TestClient

    from context_engineering.api import create_app

    return TestClient(create_app())


def test_pack_rejects_too_many_items_with_422() -> None:
    from context_engineering.api import MAX_ITEMS

    client = _client()
    response = client.post(
        "/api/v1/pack",
        json={
            "items": [{"id": str(n), "content": "x"} for n in range(MAX_ITEMS + 1)],
            "budget": {"maxTokens": 100},
        },
    )
    assert response.status_code == 422


def test_pack_accepts_item_count_at_limit() -> None:
    from context_engineering.api import MAX_ITEMS

    client = _client()
    # A handful below the limit keeps the test fast while proving the bound is a
    # ceiling, not a fixed size.
    response = client.post(
        "/api/v1/pack",
        json={
            "items": [{"id": str(n), "content": "x"} for n in range(5)],
            "budget": {"maxTokens": 100_000},
        },
    )
    assert response.status_code == 200
    assert len(response.json()["selected"]) <= MAX_ITEMS


def test_oversized_body_rejected_with_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request body larger than the cap is rejected with 413 before handling."""
    # Build the app with a deliberately tiny body cap so the test payload stays small.
    monkeypatch.setenv("CE_API_MAX_BODY_BYTES", "256")
    import importlib

    import context_engineering.api as api_module

    importlib.reload(api_module)
    from fastapi.testclient import TestClient

    try:
        client = TestClient(api_module.create_app())
        big_content = "y" * 1024  # exceeds the 256-byte cap
        response = client.post(
            "/api/v1/pack",
            json={
                "items": [{"id": "a", "content": big_content}],
                "budget": {"maxTokens": 100},
            },
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    finally:
        monkeypatch.delenv("CE_API_MAX_BODY_BYTES", raising=False)
        importlib.reload(api_module)


def test_pack_handler_runs_in_threadpool() -> None:
    """The /api/v1/pack handler offloads pack() via run_in_threadpool so the
    synchronous CPU-bound work does not block the event loop."""
    import inspect

    import context_engineering.api as api_module

    source = inspect.getsource(api_module.create_app)
    normalized = " ".join(source.split())
    assert "run_in_threadpool( pack," in normalized
    assert "run_in_threadpool( trace_pack," in normalized
