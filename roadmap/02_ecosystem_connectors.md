# Roadmap 02: Ecosystem Connectors (LangChain & LlamaIndex)

## Objective

Enable developers to use the `context-engineering` toolkit within their existing agent frameworks with zero architectural changes.

## 1. LangChain Integration (Python)

- **`CEContextMemory`**: A subclass of `BaseChatMemory`.
  - Intercepts `load_memory_variables`.
  - Runs `AgentContextManager.build_context()` on the stored messages.
  - Returns a pruned list of messages that fits the LLM's window.
- **`CECallbackHandler`**: Automatically logs context traces to the `Context Inspector` UI during a Chain run.

## 2. LlamaIndex Integration (Python)

- **`CEPostprocessor`**: A subclass of `BaseNodePostprocessor`.
  - Takes the retrieved `Nodes`.
  - Converts them to `ContextItems`.
  - Uses the `pack` algorithm to select the highest-scoring nodes based on the current query's "Budget."
- **`CEMemoryStoreAdapter`**: Allows LlamaIndex's `ChatMemoryBuffer` to use the toolkit's `SqliteStore` or `RedisStore`.

## Implementation Plan

1.  Create `python/context_engineering/extensions/` directory.
2.  Implement `langchain.py` with `CEChatMessageHistory`.
3.  Implement `llamaindex.py` with `CERetrieverPruner`.
4.  Add `extra_requirements` to `pyproject.toml` for `[langchain]` and `[llamaindex]`.

## Success Criteria

- A user can add context engineering to a LangChain agent with:
  ```python
  from context_engineering.extensions.langchain import CEContextMemory
  memory = CEContextMemory(budget=4096)
  ```
