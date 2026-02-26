from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import AnthropicAgenticTextSystem

DEFAULT_TEXT = (
    "Hello   team,\n\n"
    "Please email me at Ada.Lovelace@example.com or call +1 (415) 555-0199.\n"
    "The draft  policy has    inconsistent spacing and casing.\n\n"
    "Thanks,\nAda"
)

DEFAULT_INSTRUCTION = (
    "Normalize whitespace, redact sensitive contact details, and return a polished "
    "internal-note version of the text."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry", "live"], default="dry")
    parser.add_argument("--method", choices=["query", "client"], default="query")
    parser.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--text-file", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def load_text(args: argparse.Namespace) -> str:
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8")
    return args.text


def main() -> None:
    args = parse_args()
    source_text = load_text(args)

    system = AnthropicAgenticTextSystem()
    deterministic = system.toolkit.apply_transform(
        source_text,
        replacements=((r"\bpolicy\b", "policy"),),
    )

    payload: dict[str, object] = {
        "mode": args.mode,
        "method": args.method,
        "instruction": args.instruction,
        "deterministic_baseline": {
            "normalized_text": deterministic.normalized_text,
            "transformed_text": deterministic.transformed_text,
            "replacement_count": deterministic.replacement_count,
            "redaction_count": deterministic.redaction_count,
            "word_count": deterministic.word_count,
            "sentence_count": deterministic.sentence_count,
            "character_count": deterministic.character_count,
        },
    }

    if args.mode == "live":
        try:
            agentic = system.run_text_workflow(
                source_text=source_text,
                instruction=args.instruction,
                method=args.method,
                cwd=args.cwd or None,
                max_turns=max(1, args.max_turns),
                enable_tool_server=True,
            )
            payload["agentic"] = agentic
        except Exception as exc:  # pragma: no cover - dependency/auth dependent
            payload["agentic_error"] = str(exc)

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"Mode: {args.mode}")
    print(f"Method: {args.method}")
    print("Deterministic transformed preview:")
    print(deterministic.transformed_text[:300])

    if args.mode == "live":
        if "agentic" in payload:
            agentic = payload["agentic"]
            assert isinstance(agentic, dict)
            print("\nAnthropic agentic SDK package:", agentic.get("sdk_package"))
            print("Assistant output preview:")
            print(str(agentic.get("assistant_text", ""))[:600])
        else:
            print("\nLive agentic execution failed:", payload.get("agentic_error"))


if __name__ == "__main__":
    main()
