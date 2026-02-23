# Context Engineering (Python)

This directory contains two Python surfaces:

- `context_engineering`: core context-packing, token budgeting, memory stores, and CLI.
- `context_framework`: tri-provider orchestration and production-style domain runtimes.

## Setup

```bash
cd /Users/k/Code/context-engineering/python
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install tiktoken
```

## Core SDK (`context_engineering`)

Exports include:
- `pack`, `trace_pack`, `diff`, `estimate_tokens`
- `Budget`, `ContextItem`, `ContextPack`, `ContextTrace`
- `InMemoryStore`, `FileStore`, `SqliteStore`

### CLI

```bash
ce budget --text "hello world" --provider openai
ce pack --input /path/to/items.json --budget 4096
ce trace --input /path/to/items.json --budget 4096
ce diff --before /tmp/pack_before.json --after /tmp/pack_after.json
ce lint --schema context-item --input /path/to/items.jsonl
```

## Tri-Provider Framework (`context_framework`)

`context_framework` includes:
- Provider adapters and SDK bridges for OpenAI, Anthropic, and Cerebras.
- Ollama adapters/bridges for both native local API and OpenAI-compatible cloud mode.
- Framework bridges for LangGraph, Deep Agents, and PydanticAI.
- Anthropic agentic text-operation system with deterministic tool-server utilities.
- Pluggable vector retrieval adapters.
- Rolling context summarization support.
- Tri-provider use-case pipeline definitions.
- Production runtime commanders with:
  - signal extraction
  - adapter enrichment
  - decision routing
  - idempotent action execution
  - retry/backoff logic
  - audit logging

## Production Runtime Scripts

From `/Users/k/Code/context-engineering/python`:

### 1. SOC Incident Commander

```bash
python examples/soc_incident_commander_runtime.py --mode dry --json
python examples/soc_incident_commander_runtime.py --mode live --use-http-adapters --audit-log /tmp/soc-audit.jsonl
```

### 2. Catastrophe Claims

```bash
python examples/catastrophe_claims_runtime.py --mode dry --json
python examples/catastrophe_claims_runtime.py --mode live --use-http-adapters --audit-log /tmp/claims-audit.jsonl
```

### 3. Supply Chain Control Tower

```bash
python examples/supply_chain_control_tower_runtime.py --mode dry --json
python examples/supply_chain_control_tower_runtime.py --mode live --use-http-adapters --audit-log /tmp/supply-audit.jsonl
```

### 4. AML/KYC Fincrime

```bash
python examples/aml_kyc_fincrime_runtime.py --mode dry --json
python examples/aml_kyc_fincrime_runtime.py --mode live --use-http-adapters --audit-log /tmp/aml-audit.jsonl
```

### 5. Pharmacovigilance Events

```bash
python examples/pharmacovigilance_events_runtime.py --mode dry --json
python examples/pharmacovigilance_events_runtime.py --mode live --use-http-adapters --audit-log /tmp/pv-audit.jsonl
```

### 6. Grid Outage Response

```bash
python examples/grid_outage_response_runtime.py --mode dry --json
python examples/grid_outage_response_runtime.py --mode live --use-http-adapters --audit-log /tmp/grid-audit.jsonl
```

### 7. Emergency Operations Center

```bash
python examples/emergency_operations_center_runtime.py --mode dry --json
python examples/emergency_operations_center_runtime.py --mode live --use-http-adapters --audit-log /tmp/eoc-audit.jsonl
```

### 8. Manufacturing Root Cause and Recovery

```bash
python examples/manufacturing_root_cause_runtime.py --mode dry --json
python examples/manufacturing_root_cause_runtime.py --mode live --use-http-adapters --audit-log /tmp/mfg-audit.jsonl
```

### 9. Regulatory Change Impact

```bash
python examples/regulatory_change_impact_runtime.py --mode dry --json
python examples/regulatory_change_impact_runtime.py --mode live --use-http-adapters --audit-log /tmp/reg-audit.jsonl
```

### 10. Contract Risk Negotiation

```bash
python examples/contract_risk_negotiation_runtime.py --mode dry --json
python examples/contract_risk_negotiation_runtime.py --mode live --use-http-adapters --audit-log /tmp/contract-audit.jsonl
```

### 11. Legacy-to-Modern Migration Factory

```bash
python examples/legacy_modern_migration_runtime.py --mode dry --json
python examples/legacy_modern_migration_runtime.py --mode live --use-http-adapters --audit-log /tmp/migration-audit.jsonl
```

### 12. Contact Center Resolution Autopilot

```bash
python examples/contact_center_autopilot_runtime.py --mode dry --json
python examples/contact_center_autopilot_runtime.py --mode live --use-http-adapters --audit-log /tmp/contact-audit.jsonl
```

### 13. Clinical Operations Optimizer

```bash
python examples/clinical_operations_optimizer_runtime.py --mode dry --json
python examples/clinical_operations_optimizer_runtime.py --mode live --use-http-adapters --audit-log /tmp/clinical-audit.jsonl
```

### 14. Cross-Channel Text Governance Orchestrator

```bash
python examples/use_cases/14_text_governance_orchestrator.py --mode dry --json
python examples/use_cases/14_text_governance_orchestrator.py --mode live --json
```

The runtime scripts share common options:
- `--mode dry|live`
- `--scenario "..."`
- `--evidence-file <path>` (repeatable)
- `--json`
- `--max-parallel <n>`

## Use-Case Runner Scripts

Run a single use case:

```bash
python examples/use_cases/09_regulatory_change_impact.py --mode dry --json
```

Run all use cases:

```bash
python examples/use_cases/run_all_use_cases.py --mode dry --json
```

## Cerebras Advanced Scripts

These scripts exercise advanced Cerebras functionality (speculative decoding, perplexity, reasoning controls):

```bash
python examples/cerebras_speculative_decoding_lab.py
python examples/cerebras_perplexity_router.py
python examples/cerebras_reasoning_controls_lab.py
python examples/weird_provider_sdk_features.py
```

For live runs, configure:
- `CEREBRAS_API_KEY`
- optionally `OPENAI_API_KEY`
- optionally `ANTHROPIC_API_KEY`

## Ollama + Framework + Agentic SDK Scripts

```bash
python examples/ollama_local_cloud_bridge_demo.py --mode local --json
python examples/ollama_local_cloud_bridge_demo.py --mode cloud --json
python examples/framework_bridge_lab.py
python examples/anthropic_agentic_text_system.py --mode dry --json
python examples/anthropic_agentic_text_system.py --mode live --method query --json
python examples/anthropic_agentic_text_system.py --mode live --method client --json
python examples/live_integration_harness.py --json
```

For live runs:
- Ollama local: configure `OLLAMA_BASE_URL` and optionally `OLLAMA_MODEL`
- Ollama cloud/OpenAI-compatible endpoint: configure `OLLAMA_BASE_URL`, optionally `OLLAMA_API_KEY`, and use `--mode cloud`
- Anthropic agentic SDK: install either `claude-agent-sdk` (current) or `claude-code-sdk` (legacy)
- Harness gates:
  - `OLLAMA_RUN_LOCAL_SMOKE=1` to run local Ollama call
  - `OLLAMA_RUN_CLOUD_SMOKE=1` to run cloud/OAI-compatible Ollama call
  - `ANTHROPIC_AGENTIC_SMOKE=1` to run Anthropic agentic SDK workflow
  - `TRI_PROVIDER_LIVE_SMOKE=1` (+ `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CEREBRAS_API_KEY`) for full live tri-provider pipeline smoke
  - optional `OLLAMA_SMOKE_TIMEOUT_SECONDS` to increase/decrease live Ollama check timeout (default `90`)

The live harness auto-discovers available Ollama models via `/api/tags` and `/v1/models` and picks an installed model if `OLLAMA_MODEL` is not set.

## Testing

From `/Users/k/Code/context-engineering/python`:

```bash
pytest -q tests
pytest -q tests/test_manufacturing_runtime.py
pytest -q tests/test_regulatory_change_runtime.py
pytest -q tests/test_contract_negotiation_runtime.py
pytest -q tests/test_legacy_modern_migration_runtime.py
pytest -q tests/test_contact_center_autopilot_runtime.py
pytest -q tests/test_clinical_operations_runtime.py
pytest -q tests/test_framework_bridges.py
pytest -q tests/test_anthropic_agentic_text_system.py
pytest -q tests/test_live_integration_harness.py
python -m compileall -q context_framework examples tests
```
