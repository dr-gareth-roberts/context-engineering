# @ce/cli

CLI for context packing, tracing, diffing, linting, and token budget estimation.

## Installation

```bash
npm install -g @ce/cli
```

Or run via npx:

```bash
npx @ce/cli pack -i items.json -b 4096
```

## Commands

### pack

Pack context items into a token budget.

```bash
ce pack -i items.json -b 4096 -p openai
ce pack -i items.jsonl -b 8000 --json
cat items.json | ce pack -i - -b 4096
```

### trace

Pack with a step-by-step decision trace (include/exclude/compress per item).

```bash
ce trace -i items.json -b 4096
ce trace -i items.json -b 4096 --json
```

### diff

Compare two context packs or item lists.

```bash
ce diff --before old.json --after new.json
ce diff --before old.json --after new.json --json
```

### lint

Validate JSON/JSONL against a schema.

```bash
ce lint -s context-item -i items.json
ce lint -s context-pack -i pack.json
ce lint -s context-item -i items.jsonl
```

Schemas: `context-item`, `context-pack`, `context-plan`, `context-trace`, `memory-item`

### budget

Estimate token count for text or a file.

```bash
ce budget -t "How many tokens is this?"
ce budget -f document.txt -p openai
```

## Common Options

| Flag | Description | Default |
|---|---|---|
| `-i, --input <file>` | Input file path (use `-` for stdin) | -- |
| `-b, --budget <n>` | Token budget | `4096` |
| `-p, --provider <name>` | Estimator: `openai`, `anthropic`, `heuristic` | `heuristic` |
| `--json` | Force JSON output | off |
| `--no-color` | Disable colored output | off |

## Input Format

Items JSON (array or `{ items: [...] }`):

```json
[
  { "id": "ctx-1", "content": "Some context", "priority": 8 },
  { "id": "ctx-2", "content": "More context", "priority": 3 }
]
```

Or JSONL (one item per line).

## License

MIT
