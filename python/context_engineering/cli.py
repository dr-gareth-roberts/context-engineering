from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, List
from jsonschema import Draft202012Validator, RefResolver

from .core import Budget, ContextItem, pack, trace_pack, diff, estimate_tokens
from .placement import place_items, effective_budget, ATTENTION_PROFILES
from .quality import analyze_context


def _is_tty():
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


class _fmt:
    @staticmethod
    def _wrap(code, text):
        if not _is_tty() or os.environ.get("NO_COLOR"):
            return text
        return f"\033[{code}m{text}\033[0m"

    @staticmethod
    def bold(text): return _fmt._wrap("1", text)
    @staticmethod
    def red(text): return _fmt._wrap("31", text)
    @staticmethod
    def green(text): return _fmt._wrap("32", text)
    @staticmethod
    def cyan(text): return _fmt._wrap("36", text)
    @staticmethod
    def dim(text): return _fmt._wrap("2", text)
    @staticmethod
    def success(text): return _fmt._wrap("32", f"OK {text}")
    @staticmethod
    def error(text): return _fmt._wrap("31", f"ERR {text}")


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
    if isinstance(data, dict) and isinstance(data.get("selected"), list):
        items = [ContextItem.model_validate(item) for item in data["selected"]]
        items.extend(ContextItem.model_validate(item) for item in data.get("dropped", []))
        return items

    raise ValueError("Invalid items file: expected array, { items: [] }, or { selected: [] }")


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

    # If data is an array and schema expects an object, validate each element
    if isinstance(data, list):
        schema_type = schema.get("type")
        if schema_type == "object" or schema_type is None:
            all_errors = []
            for idx, item in enumerate(data):
                errors = [f"[{idx}] {e.message}" for e in validator.iter_errors(item)]
                all_errors.extend(errors)
            return all_errors

    errors = [error.message for error in validator.iter_errors(data)]
    return errors


def _model_dump_json(obj: Any) -> str:
    """Dump a Pydantic model to JSON, excluding None values."""
    if hasattr(obj, "model_dump_json"):
        return obj.model_dump_json(by_alias=True, indent=2, exclude_none=True)
    return json.dumps(obj, indent=2, default=lambda o: o.model_dump(by_alias=True, exclude_none=True) if hasattr(o, "model_dump") else o)


def cmd_pack(args: argparse.Namespace) -> None:
    if args.input == "-":
        raw = sys.stdin.read()
        items_data = json.loads(raw)
        if isinstance(items_data, list):
            items = [ContextItem(**i) if isinstance(i, dict) else i for i in items_data]
        else:
            items = [ContextItem(**i) if isinstance(i, dict) else i for i in items_data.get("items", [])]
    else:
        items = _load_items(args.input)
    budget = Budget(maxTokens=args.budget)
    result = pack(items, budget, allow_compression=True, provider=args.provider)
    if not _is_tty():
        print(_model_dump_json(result))
    else:
        print(f"{_fmt.bold(f'Selected {len(result.selected)} items')}"
              f" {_fmt.dim(f'(dropped {len(result.dropped)})')}")
        print(f"Total tokens: {_fmt.cyan(str(result.total_tokens))}")


def cmd_trace(args: argparse.Namespace) -> None:
    if args.input == "-":
        raw = sys.stdin.read()
        items_data = json.loads(raw)
        if isinstance(items_data, list):
            items = [ContextItem(**i) if isinstance(i, dict) else i for i in items_data]
        else:
            items = [ContextItem(**i) if isinstance(i, dict) else i for i in items_data.get("items", [])]
    else:
        items = _load_items(args.input)
    budget = Budget(maxTokens=args.budget)
    result = trace_pack(items, budget, allow_compression=True, provider=args.provider)
    if not _is_tty():
        print(_model_dump_json(result))
    else:
        print(_fmt.bold(f"Trace: {len(result.steps)} steps"))
        for step in result.steps:
            marker = _fmt.green("+ ") if step.decision == "include" else _fmt.red("- ")
            print(f"  {marker}{step.id}: {step.decision} {_fmt.dim(step.reason or '')}")


def cmd_diff(args: argparse.Namespace) -> None:
    with open(args.before, "r", encoding="utf-8") as handle:
        before = json.load(handle)
    with open(args.after, "r", encoding="utf-8") as handle:
        after = json.load(handle)
    result = diff(before, after)
    if not _is_tty():
        print(json.dumps(result, default=lambda o: o.model_dump(by_alias=True, exclude_none=True) if hasattr(o, "model_dump") else o, indent=2))
    else:
        print(_fmt.green(f"  + {len(result['added'])} added"))
        print(_fmt.red(f"  - {len(result['removed'])} removed"))
        print(_fmt.cyan(f"  ~ {len(result['changed'])} changed"))
        print(_fmt.dim(f"  = {len(result['kept'])} kept"))


def cmd_budget(args: argparse.Namespace) -> None:
    text = args.text
    if not text and args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            text = handle.read()
    if not text:
        raise SystemExit("Provide --text or --file")
    tokens = estimate_tokens(text, provider=args.provider)
    if not _is_tty():
        print(tokens)
    else:
        print(f"Estimated tokens: {_fmt.cyan(str(tokens))}")


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


def cmd_place(args: argparse.Namespace) -> None:
    items = _load_items(args.input)
    placed = place_items(
        items,
        strategy=args.strategy,
        model=args.model,
    )
    if not _is_tty():
        print(json.dumps(
            [i.model_dump(by_alias=True, exclude_none=True) for i in placed],
            indent=2,
        ))
    else:
        print(_fmt.bold(f"Placed {len(placed)} items ({args.strategy})"))
        for i, item in enumerate(placed):
            print(f"  Position {i}: {item.id} (score={item.score or 0})")


def cmd_quality(args: argparse.Namespace) -> None:
    items = _load_items(args.input)
    quality = analyze_context(items)
    if not _is_tty():
        print(json.dumps({
            "itemCount": quality.item_count,
            "totalTokens": quality.total_tokens,
            "density": quality.density,
            "diversity": quality.diversity,
            "freshness": quality.freshness,
            "redundancy": quality.redundancy,
            "overall": quality.overall,
        }, indent=2))
    else:
        print(_fmt.bold("Context Quality"))
        print(f"  Items:      {quality.item_count}")
        print(f"  Tokens:     {quality.total_tokens}")
        print(f"  Density:    {_fmt.cyan(str(quality.density))}")
        print(f"  Diversity:  {_fmt.cyan(str(quality.diversity))}")
        print(f"  Freshness:  {_fmt.cyan(str(quality.freshness))}")
        print(f"  Redundancy: {_fmt.cyan(str(quality.redundancy))}")
        print(f"  Overall:    {_fmt.bold(str(quality.overall))}")


def cmd_effective_budget(args: argparse.Namespace) -> None:
    budget = effective_budget(args.tokens, model=args.model)
    if not _is_tty():
        print(budget)
    else:
        model = args.model or "default"
        profile = ATTENTION_PROFILES.get(model, ATTENTION_PROFILES["default"])
        print(f"Model:    {_fmt.cyan(model)}")
        print(f"Capacity: {_fmt.cyan(f'{profile.effective_capacity:.0%}')}")
        print(f"Effective: {_fmt.bold(str(budget))} / {args.tokens} tokens")


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

    place_parser = subparsers.add_parser("place", help="Attention-optimized item placement")
    place_parser.add_argument("-i", "--input", required=True)
    place_parser.add_argument("-s", "--strategy", default="attention-optimized",
                              choices=["score-order", "attention-optimized"])
    place_parser.add_argument("-m", "--model", default="default")
    place_parser.set_defaults(func=cmd_place)

    quality_parser = subparsers.add_parser("quality", help="Analyze context quality")
    quality_parser.add_argument("-i", "--input", required=True)
    quality_parser.set_defaults(func=cmd_quality)

    eb_parser = subparsers.add_parser("effective-budget", help="Compute effective token budget")
    eb_parser.add_argument("-t", "--tokens", type=int, required=True)
    eb_parser.add_argument("-m", "--model", default=None)
    eb_parser.set_defaults(func=cmd_effective_budget)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
