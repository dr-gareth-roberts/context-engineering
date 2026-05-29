# Getting Started

## Installation

### TypeScript

```bash
# Core (required)
npm install @context-engineering/core

# Optional packages — install only what you need
npm install @context-engineering/providers    # OpenAI/Anthropic token estimators
npm install @context-engineering/memory       # Persistent memory stores
npm install @context-engineering/council      # Multi-model deliberation
npm install @context-engineering/adversarial  # Red-team testing
npm install @context-engineering/compiler     # Declarative context compilation
npm install @context-engineering/drift        # Quality monitoring
npm install @context-engineering/immune       # Failure pattern detection
npm install @context-engineering/entangle     # Multi-agent context sharing
npm install @context-engineering/time-travel  # Context state branching
npm install @context-engineering/router       # Model routing by complexity
npm install @context-engineering/adaptive     # Adaptive weight learning
npm install @context-engineering/rag          # Context-aware retrieval
npm install @context-engineering/debugger     # Context diagnostics
npm install @context-engineering/frameworks   # LangChain/LlamaIndex middleware
npm install @context-engineering/sdk-interceptors  # OpenAI/Anthropic SDK wrappers
npm install -g @context-engineering/cli       # CLI tools
```

### Python

```bash
pip install context-engineering

# Optional extras
pip install context-engineering[redis]     # Redis memory store
pip install context-engineering[postgres]  # Postgres memory store
```

The Python SDK includes all features in a single package. No separate installs needed.

## Prerequisites

- **Node.js** 18+ (CI tests against Node 20 and 22)
- **Python** 3.11+
- **pnpm** 10+ (for monorepo development)

## Development Setup (Contributors)

```bash
git clone https://github.com/dr-gareth-roberts/context-engineering.git
cd context-engineering

# TypeScript
pnpm install
pnpm build:all

# Python
cd python
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

Verify:

```bash
pnpm test:packages    # 1,264 TypeScript tests
python -m pytest      # 908 Python tests
pnpm check:all        # Type checking
```

## Your First Pack

The simplest useful thing: pack items into a token budget.

```ts
import { pack } from "@context-engineering/core";

const items = [
  {
    id: "system",
    content: "You are a helpful assistant.",
    priority: 10,
    kind: "system",
  },
  {
    id: "doc1",
    content: "The API supports GET and POST methods...",
    priority: 7,
    kind: "retrieval",
  },
  {
    id: "doc2",
    content: "Rate limits are 100 requests per minute...",
    priority: 5,
    kind: "retrieval",
  },
  {
    id: "history",
    content: "User asked about authentication yesterday...",
    priority: 3,
    kind: "conversation",
  },
  {
    id: "query",
    content: "How do I authenticate API requests?",
    priority: 9,
    kind: "query",
  },
];

const result = pack(items, { maxTokens: 500 });

console.log(result.selected.map(i => i.id)); // which items fit
console.log(result.dropped.map(i => i.id)); // which were cut
console.log(result.totalTokens); // tokens used
```

Items are scored by `priority * 1.0 + recency * 0.7 + salience * 0.5`, sorted by score, and greedily selected until the budget is exhausted.

## Next Steps

- [Core Concepts](./Core-Concepts.md) — understand items, scoring, and packing
- [Your First Pipeline](./First-Pipeline.md) — chain operations together
- [Package Overview](./Package-Overview.md) — see all 17 packages
