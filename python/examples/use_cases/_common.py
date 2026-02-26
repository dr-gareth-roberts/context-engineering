from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import USE_CASE_INDEX, TriProviderPipeline


def parse_args(default_scenario: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["dry", "live"],
        default="dry",
        help="Run dry simulation or live provider calls.",
    )
    parser.add_argument(
        "--scenario",
        default=default_scenario,
        help="Primary scenario text to run through the tri-provider pipeline.",
    )
    parser.add_argument(
        "--evidence-file",
        action="append",
        default=[],
        help="Path to a text file to include as evidence document. Can be repeated.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit report as JSON.",
    )
    return parser.parse_args()


def load_evidence(files: Sequence[str]) -> list[str]:
    docs: list[str] = []
    for path in files:
        value = Path(path).read_text(encoding="utf-8").strip()
        if value:
            docs.append(value)
    return docs


def run_use_case(
    *,
    use_case_id: str,
    default_scenario: str,
) -> None:
    args = parse_args(default_scenario)
    spec = USE_CASE_INDEX[use_case_id]
    pipeline = TriProviderPipeline(spec)
    report = pipeline.run(
        scenario=args.scenario,
        evidence_documents=tuple(load_evidence(args.evidence_file)),
        mode=args.mode,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    print(f"Use case: {report.title} ({report.use_case_id})")
    print(f"Mode: {report.mode}")
    print(f"Context tokens: {report.context_tokens_used}/{report.context_token_budget}")
    print("")
    print("OpenAI stage preview:")
    print(report.openai_stage.response_preview)
    print("")
    print("Anthropic stage preview:")
    print(report.anthropic_stage.response_preview)
    print("")
    print("Top ranked actions:")
    if report.ranked_actions:
        for idx, row in enumerate(report.ranked_actions[:3], start=1):
            score = f"{row.score:.4f}"
            ppl = f" perplexity={row.perplexity:.4f}" if row.perplexity is not None else ""
            print(f"{idx}. score={score}{ppl} source={row.source}")
            print(f"   {row.action}")
            print(f"   rationale: {row.rationale}")
    else:
        print("No ranked actions produced.")
    print("")
    print("Final plan:")
    print(report.final_plan)
    if report.speculative_metrics is not None:
        m = report.speculative_metrics
        print("")
        print(
            "Speculative metrics:",
            f"accepted={m.accepted_prediction_tokens}",
            f"rejected={m.rejected_prediction_tokens}",
            f"acceptance_rate={m.acceptance_rate:.2%}",
        )
    if report.warnings:
        print("")
        print("Warnings:")
        for warning in report.warnings:
            print(f"- {warning}")
    if report.errors:
        print("")
        print("Errors:")
        for err in report.errors:
            print(f"- {err}")
