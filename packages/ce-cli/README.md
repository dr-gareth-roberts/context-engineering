# @context-engineering/cli

CLI for context packing, tracing, diffing, placement, quality analysis, cost estimation, agent handoff, linting, and token budgets.

## Installation

```bash
npm install -g @context-engineering/cli
```

Or run via npx:

```bash
npx @context-engineering/cli pack -i items.json -b 4096
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

### place

Pack and reorder items for optimal model attention placement.

```bash
ce place -i items.json -b 4096 -s attention-optimized -m claude
ce place -i items.json -b 8000 -s score-order
```

### quality

Analyze context quality (density, diversity, freshness, redundancy).

```bash
ce quality -i items.json -b 4096
ce quality -i items.json -b 8000 --json
```

### effective-budget

Calculate effective token budget accounting for context degradation.

```bash
ce effective-budget -t 200000 -m claude    # → 140,000 (70%)
ce effective-budget -t 128000 -m gpt4      # → 83,200 (65%)
```

### handoff

Create a BEADS JSONL handoff from context items for agent-to-agent transfer.

```bash
ce handoff -i items.json -b 8000 -o .beads/issues.jsonl --agent agent-1
ce handoff -i items.json -b 8000 --cache-topology --include-dropped
ce handoff -i items.json -b 4096    # outputs JSONL to stdout
```

### pickup

Pick up context from a BEADS JSONL handoff.

```bash
ce pickup -i .beads/issues.jsonl
ce pickup -i .beads/issues.jsonl --ready   # only open, non-blocked items
```

### cost

Estimate API costs with prefix cache savings.

```bash
ce cost -i items.json -m claude-sonnet-4-6 -b 8000
ce cost -i items.json -m claude-opus-4-6 --requests 10000 --requests-per-day 500
ce cost -i items.json -m gpt-4.1 --output-tokens 1000 --json
```

Supported models: `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`, `gpt-4.1`, `gpt-4.1-mini`, `gpt-4o`, `o3`, `o4-mini`

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

| Flag                    | Description                                   | Default     |
| ----------------------- | --------------------------------------------- | ----------- |
| `-i, --input <file>`    | Input file path (use `-` for stdin)           | --          |
| `-b, --budget <n>`      | Token budget                                  | `4096`      |
| `-p, --provider <name>` | Estimator: `openai`, `anthropic`, `heuristic` | `heuristic` |
| `-m, --model <name>`    | Model for placement/cost/budget               | varies      |
| `--json`                | Force JSON output                             | off         |
| `--no-color`            | Disable colored output                        | off         |

## Input Format

Items JSON (array or `{ items: [...] }`):

```json
[
  { "id": "ctx-1", "content": "Some context", "kind": "system", "priority": 8 },
  {
    "id": "ctx-2",
    "content": "More context",
    "kind": "retrieval",
    "priority": 3
  }
]
```

Or JSONL (one item per line).

## License

MIT
