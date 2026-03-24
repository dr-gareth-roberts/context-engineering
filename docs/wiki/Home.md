# Context Engineering Toolkit — Wiki

## What is this?

A dual TypeScript/Python toolkit for managing what goes into LLM context windows. The core problem: given a finite token budget and a pile of potentially useful context (documents, conversation history, tool definitions, memories), which items should you include, in what order, and at what cost?

This toolkit provides algorithms, strategies, and infrastructure for that decision at every level — from basic packing to multi-model deliberation to adversarial testing of your context pipeline.

## Quick Navigation

### Getting Started

- [Installation & Setup](./Getting-Started.md)
- [Core Concepts](./Core-Concepts.md)
- [Your First Pipeline](./First-Pipeline.md)

### Package Guide

- [Package Overview](./Package-Overview.md) — all 17 packages at a glance
- [Core Packages](./Core-Packages.md) — ce-core, ce-providers, ce-memory, ce-cli
- [Multi-Model & Multi-Agent](./Multi-Model.md) — ce-council, ce-entangle, ce-router
- [Quality & Safety](./Quality-Safety.md) — ce-adversarial, ce-immune, ce-debugger, ce-drift
- [Optimization](./Optimization.md) — ce-compiler, ce-adaptive, ce-time-travel
- [Integration](./Integration.md) — ce-sdk-interceptors, ce-frameworks, ce-rag

### Concepts & Guides

- [Scoring & Relevance](./Scoring.md)
- [Cache Topology](./Cache-Topology.md)
- [Budget Allocation](./Budget-Allocation.md)
- [Causal Compaction](./Causal-Compaction.md)
- [BEADS Agent Handoff](./BEADS-Handoff.md)
- [Error Handling](./Error-Handling.md)

### Advanced Topics

- [Multi-Model Deliberation Strategies](./Deliberation-Strategies.md)
- [Adversarial Testing Guide](./Adversarial-Testing.md)
- [Context Compilation](./Context-Compilation.md)
- [Drift Detection in Production](./Drift-Detection.md)
- [Multi-Agent Entanglement](./Multi-Agent-Entanglement.md)
- [Context Immune System](./Context-Immune-System.md)
- [Context Time Travel](./Context-Time-Travel.md)

### Reference

- [TypeScript API Reference](./API-Reference-TypeScript.md)
- [Python API Reference](./API-Reference-Python.md)
- [CLI Reference](./CLI-Reference.md)
- [Architecture](./Architecture.md)
- [Contributing](../CONTRIBUTING.md)
- [Changelog](../../CHANGELOG.md)
