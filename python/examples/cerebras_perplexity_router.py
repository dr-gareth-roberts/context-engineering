from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import CerebrasSDKBridge, ContextManager


def _build_packet():
    manager = ContextManager(default_token_budget=4096, reserved_response_tokens=512)
    manager.add_system(
        "You are a reliability architect. Generate concise recommendations with explicit tradeoffs."
    )
    manager.add_message(
        "user",
        "Pick the best retry-policy draft and refine it for production rollout.",
    )
    return manager.build_context("retry policy draft ranking")


def _print_dry_run_example(bridge: CerebrasSDKBridge, candidates: list[str]) -> None:
    # Offline math demo using synthetic logprobs, so script is useful even without API keys.
    synthetic = {
        candidates[0]: [-0.65, -0.72, -0.61],
        candidates[1]: [-0.28, -0.35, -0.22],
        candidates[2]: [-0.49, -0.43, -0.51],
    }
    rows: list[tuple[str, float]] = []
    for candidate, logs in synthetic.items():
        result = bridge.compute_perplexity(logs)
        rows.append((candidate, result.perplexity))
    rows.sort(key=lambda row: row[1])

    print("Dry-run ranking with synthetic logprobs (lower perplexity is better):")
    for idx, (candidate, perplexity) in enumerate(rows, start=1):
        print(f"{idx}. ppl={perplexity:.4f}  {candidate}")


def _render_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict):
                chunks.append(str(block.get("text", "")))
            else:
                chunks.append(str(block))
        return " ".join(chunk for chunk in chunks if chunk).strip()
    return str(content)


def _run_live(bridge: CerebrasSDKBridge, packet: Any, candidates: list[str]) -> None:
    from cerebras.cloud.sdk import Cerebras  # type: ignore

    client = Cerebras()
    ranking = bridge.score_candidates_by_perplexity(
        client,
        prefix="Evaluate fluency and likelihood for this retry policy draft:",
        candidates=candidates,
    )

    print("Live perplexity ranking:")
    for idx, (candidate, result) in enumerate(ranking, start=1):
        print(
            f"{idx}. ppl={result.perplexity:.4f} "
            f"avg_neg_logprob={result.average_negative_logprob:.4f} "
            f"candidate={candidate}"
        )

    best_candidate = ranking[0][0]
    response = bridge.create_speculative_chat(
        client,
        packet,
        predicted_output=best_candidate,
        prompt=(
            "Refine this draft for production, add one caveat and one rollback checkpoint."
        ),
        max_completion_tokens=260,
        temperature=0.1,
    )
    message = response.choices[0].message  # type: ignore[index]
    final_text = _render_text(getattr(message, "content", ""))
    metrics = bridge.extract_speculative_decoding_metrics(response)
    print("\nRefined output preview:")
    print(final_text[:220])
    if metrics:
        print(
            "Speculative acceptance:",
            f"{metrics.accepted_prediction_tokens}/{metrics.total_prediction_tokens}",
            f"({metrics.acceptance_rate:.2%})",
        )


def main() -> None:
    bridge = CerebrasSDKBridge(
        model="qwen-3-32b",
        service_tier="priority",
        reasoning_effort="low",
        reasoning_format="none",
    )
    packet = _build_packet()
    candidates = [
        "Use exponential backoff with jitter and cap retries at 7 attempts.",
        "Use exponential backoff with jitter, cap retries at 5, enforce idempotency keys, and alert on retry saturation.",
        "Use fixed 2-second retries for all failures and keep retrying until success.",
    ]

    if not os.getenv("CEREBRAS_API_KEY"):
        _print_dry_run_example(bridge, candidates)
        print("\nSet CEREBRAS_API_KEY to run live perplexity routing + speculative refinement.")
        return

    try:
        _run_live(bridge, packet, candidates)
    except Exception as exc:  # pragma: no cover - optional live path
        print(f"Live Cerebras run failed: {exc}")


if __name__ == "__main__":
    main()
