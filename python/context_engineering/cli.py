from __future__ import annotations

import argparse
import json
import os
from typing import Any, List
from jsonschema import Draft202012Validator, RefResolver

from .core import Budget, ContextItem, pack, trace_pack, diff, estimate_tokens


def _load_items(path: str) -> List[ContextItem]:
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read().strip()

    if not content:
        return []

    if path.endswith(".jsonl"):
        return [ContextItem.model_validate(json.loads(line)) for line in content.splitlines() if line.strip()]

    data = json.loads(content)
    if isinstance(data, list):
        return [ContextItem.model_validate(item) for item in data]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [ContextItem.model_validate(item) for item in data["items"]]

    raise ValueError("Invalid items file")


def _find_schema_dir(start: str) -> str:
    current = start
    for _ in range(8):
        candidate = os.path.join(current, "schemas")
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    raise RuntimeError("Could not locate schemas directory")


def _load_schema(name: str) -> Any:
    schema_dir = _find_schema_dir(os.getcwd())
    filename = {
        "context-item": "context-item.schema.json",
        "context-plan": "context-plan.schema.json",
        "context-pack": "context-pack.schema.json",
        "context-trace": "context-trace.schema.json",
        "memory-item": "memory-item.schema.json",
    }[name]
    schema_path = os.path.join(schema_dir, filename)
    with open(schema_path, "r", encoding="utf-8") as handle:
        return json.load(handle)

def _load_all_schemas() -> dict[str, Any]:
    schema_dir = _find_schema_dir(os.getcwd())
    schemas = {}
    for filename in [
        "context-item.schema.json",
        "context-plan.schema.json",
        "context-pack.schema.json",
        "context-trace.schema.json",
        "memory-item.schema.json",
    ]:
        path = os.path.join(schema_dir, filename)
        with open(path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
            if "$id" in schema:
                schemas[schema["$id"]] = schema
    return schemas


def _lint(schema_name: str, data: Any) -> List[str]:
    schema = _load_schema(schema_name)
    store = _load_all_schemas()
    resolver = RefResolver.from_schema(schema, store=store)
    validator = Draft202012Validator(schema, resolver=resolver)
    errors = [error.message for error in validator.iter_errors(data)]
    return errors


def cmd_pack(args: argparse.Namespace) -> None:
    items = _load_items(args.input)
    budget = Budget(maxTokens=args.budget)
    result = pack(items, budget, allow_compression=True, provider=args.provider)
    print(result.model_dump_json(by_alias=True, indent=2))


def cmd_trace(args: argparse.Namespace) -> None:
    items = _load_items(args.input)
    budget = Budget(maxTokens=args.budget)
    result = trace_pack(items, budget, allow_compression=True, provider=args.provider)
    print(result.model_dump_json(by_alias=True, indent=2))


def cmd_diff(args: argparse.Namespace) -> None:
    with open(args.before, "r", encoding="utf-8") as handle:
        before = json.load(handle)
    with open(args.after, "r", encoding="utf-8") as handle:
        after = json.load(handle)
    result = diff(before, after)
    print(json.dumps(result, default=lambda o: o.model_dump(by_alias=True) if hasattr(o, "model_dump") else o, indent=2))


def cmd_budget(args: argparse.Namespace) -> None:
    text = args.text
    if not text and args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            text = handle.read()
    if not text:
        raise SystemExit("Provide --text or --file")
    tokens = estimate_tokens(text, provider=args.provider)
    print(tokens)


def cmd_lint(args: argparse.Namespace) -> None:
    with open(args.input, "r", encoding="utf-8") as handle:
        raw = handle.read().strip()

    if not raw:
        raise SystemExit("Input file is empty")

    if args.input.endswith(".jsonl"):
        for idx, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            data = json.loads(line)
            errors = _lint(args.schema, data)
            if errors:
                raise SystemExit(f"Line {idx} failed validation: {errors}")
        print("All lines valid")
        return

    data = json.loads(raw)
    errors = _lint(args.schema, data)
    if errors:
        raise SystemExit("Validation failed: " + "; ".join(errors))
    print("Valid")


def main() -> None:
    parser = argparse.ArgumentParser(prog="ce", description="Context engineering CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pack_parser = subparsers.add_parser("pack", help="Pack context items")
    pack_parser.add_argument("-i", "--input", required=True)
    pack_parser.add_argument("-b", "--budget", type=int, default=4096)
    pack_parser.add_argument("-p", "--provider", default=None)
    pack_parser.set_defaults(func=cmd_pack)

    trace_parser = subparsers.add_parser("trace", help="Pack with trace output")
    trace_parser.add_argument("-i", "--input", required=True)
    trace_parser.add_argument("-b", "--budget", type=int, default=4096)
    trace_parser.add_argument("-p", "--provider", default=None)
    trace_parser.set_defaults(func=cmd_trace)

    diff_parser = subparsers.add_parser("diff", help="Diff packs or items")
    diff_parser.add_argument("--before", required=True)
    diff_parser.add_argument("--after", required=True)
    diff_parser.set_defaults(func=cmd_diff)

    budget_parser = subparsers.add_parser("budget", help="Estimate tokens")
    budget_parser.add_argument("-t", "--text")
    budget_parser.add_argument("-f", "--file")
    budget_parser.add_argument("-p", "--provider", default="heuristic")
    budget_parser.set_defaults(func=cmd_budget)

    lint_parser = subparsers.add_parser("lint", help="Validate data")
    lint_parser.add_argument("-s", "--schema", required=True)
    lint_parser.add_argument("-i", "--input", required=True)
    lint_parser.set_defaults(func=cmd_lint)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
