from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from .tri_provider_pipeline import TriProviderPipeline


@dataclass(slots=True, frozen=True)
class FrameworkRunResult:
    framework: str
    input: Any
    output: Any
    metadata: dict[str, Any] = field(default_factory=dict)


def _resolve_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    raise RuntimeError(
        "Received coroutine output while an event loop is already running. "
        "Use the async framework method directly instead of the sync wrapper."
    )


@dataclass(slots=True)
class LangGraphBridge:
    """
    Lightweight bridge for integrating TriProviderPipeline with LangGraph.

    Imports are optional and runtime checks are explicit so this module can be
    used in environments without LangGraph installed.
    """

    @staticmethod
    def create_state_graph(state_schema: Any) -> Any:
        try:
            from langgraph.graph import StateGraph  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "langgraph is not installed. Install with `pip install langgraph`."
            ) from exc
        return StateGraph(state_schema)

    @staticmethod
    def compile_graph(graph: Any, **kwargs: Any) -> Any:
        if not hasattr(graph, "compile"):
            raise TypeError("LangGraph graph object must expose a compile() method")
        return graph.compile(**kwargs)

    @staticmethod
    def invoke(
        compiled_graph: Any,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
    ) -> Any:
        if not hasattr(compiled_graph, "invoke"):
            raise TypeError("Compiled graph must expose an invoke() method")
        if config is None:
            return compiled_graph.invoke(state)
        return compiled_graph.invoke(state, config=config)

    @staticmethod
    def stream(
        compiled_graph: Any,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        stream_mode: str | None = None,
    ) -> Any:
        if not hasattr(compiled_graph, "stream"):
            raise TypeError("Compiled graph must expose a stream() method")
        kwargs: dict[str, Any] = {}
        if config is not None:
            kwargs["config"] = config
        if stream_mode is not None:
            kwargs["stream_mode"] = stream_mode
        return compiled_graph.stream(state, **kwargs)

    @staticmethod
    def make_tri_provider_node(
        pipeline: TriProviderPipeline,
        *,
        scenario_key: str = "scenario",
        evidence_key: str = "evidence_documents",
        mode_key: str = "mode",
        metadata_key: str = "metadata",
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def _node(state: dict[str, Any]) -> dict[str, Any]:
            scenario = str(state.get(scenario_key, "")).strip()
            if not scenario:
                raise ValueError(f"state must include non-empty '{scenario_key}'")
            evidence = tuple(str(value) for value in (state.get(evidence_key) or ()))
            mode = str(state.get(mode_key, "dry"))
            metadata = dict(state.get(metadata_key) or {})

            report = pipeline.run(
                scenario=scenario,
                evidence_documents=evidence,
                mode="live" if mode == "live" else "dry",
                metadata=metadata,
            )
            return {
                "tri_provider_report": report.to_dict(),
                "tri_provider_final_plan": report.final_plan,
                "tri_provider_ranked_actions": [
                    {
                        "action": row.action,
                        "score": row.score,
                        "source": row.source,
                        "rationale": row.rationale,
                        "perplexity": row.perplexity,
                    }
                    for row in report.ranked_actions
                ],
            }

        return _node


@dataclass(slots=True)
class DeepAgentsBridge:
    """
    Bridge for Deep Agents frameworks.

    Official `deepagents` API uses `create_deep_agent`, but this class also
    supports common alternatives (`create_agent`, `Agent`) to stay robust across
    package versions.
    """

    @staticmethod
    def create_agent(*args: Any, **kwargs: Any) -> Any:
        try:
            import deepagents  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "deepagents is not installed. Install with `pip install deepagents`."
            ) from exc

        if hasattr(deepagents, "create_deep_agent"):
            return deepagents.create_deep_agent(*args, **kwargs)
        if hasattr(deepagents, "create_agent"):
            return deepagents.create_agent(*args, **kwargs)
        if hasattr(deepagents, "Agent"):
            return deepagents.Agent(*args, **kwargs)
        raise RuntimeError(
            "Unsupported deepagents package shape: missing create_deep_agent/create_agent/Agent"
        )

    @staticmethod
    def run(agent: Any, task: str, **kwargs: Any) -> FrameworkRunResult:
        run_method = getattr(agent, "run", None)
        if run_method is not None:
            output = _resolve_awaitable(run_method(task, **kwargs))
            return FrameworkRunResult(
                framework="deepagents",
                input=task,
                output=output,
                metadata={"method": "run"},
            )

        invoke_method = getattr(agent, "invoke", None)
        if invoke_method is not None:
            payload = {"messages": [{"role": "user", "content": task}]}
            output = _resolve_awaitable(invoke_method(payload, **kwargs))
            return FrameworkRunResult(
                framework="deepagents",
                input=task,
                output=output,
                metadata={"method": "invoke"},
            )

        ainvoke_method = getattr(agent, "ainvoke", None)
        if ainvoke_method is not None:
            payload = {"messages": [{"role": "user", "content": task}]}
            output = _resolve_awaitable(ainvoke_method(payload, **kwargs))
            return FrameworkRunResult(
                framework="deepagents",
                input=task,
                output=output,
                metadata={"method": "ainvoke"},
            )

        for method_name in ("chat", "respond"):
            method = getattr(agent, method_name, None)
            if method is None:
                continue
            output = _resolve_awaitable(method(task, **kwargs))
            return FrameworkRunResult(
                framework="deepagents",
                input=task,
                output=output,
                metadata={"method": method_name},
            )

        raise TypeError("Deep agent object must expose run/invoke/ainvoke/chat/respond")

    @staticmethod
    def make_tri_provider_tool(
        pipeline: TriProviderPipeline,
    ) -> Callable[[str, list[str] | None, str], dict[str, Any]]:
        def _tool(
            scenario: str,
            evidence_documents: list[str] | None = None,
            mode: str = "dry",
        ) -> dict[str, Any]:
            report = pipeline.run(
                scenario=scenario,
                evidence_documents=tuple(evidence_documents or ()),
                mode="live" if mode == "live" else "dry",
            )
            return report.to_dict()

        return _tool


@dataclass(slots=True)
class PydanticAIBridge:
    """
    Optional bridge for pydantic-ai agents.

    Supports `Agent.run_sync` and async `Agent.run` execution, with helpers to
    extract commonly used output fields.
    """

    @staticmethod
    def create_agent(
        model: str,
        *,
        system_prompt: str,
        output_type: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        try:
            from pydantic_ai import Agent  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "pydantic-ai is not installed. Install with `pip install pydantic-ai`."
            ) from exc

        agent_kwargs: dict[str, Any] = {"system_prompt": system_prompt, **kwargs}
        if output_type is not None:
            agent_kwargs["output_type"] = output_type

        try:
            return Agent(model, **agent_kwargs)
        except TypeError:
            return Agent(model=model, **agent_kwargs)

    @staticmethod
    def run_sync(agent: Any, prompt: str, **kwargs: Any) -> FrameworkRunResult:
        method = getattr(agent, "run_sync", None)
        if method is not None:
            output = method(prompt, **kwargs)
            return FrameworkRunResult(
                framework="pydantic_ai",
                input=prompt,
                output=output,
                metadata={"method": "run_sync"},
            )

        method = getattr(agent, "run", None)
        if method is None:
            raise TypeError("PydanticAI agent must expose run_sync() or run()")

        output = _resolve_awaitable(method(prompt, **kwargs))
        return FrameworkRunResult(
            framework="pydantic_ai",
            input=prompt,
            output=output,
            metadata={"method": "run"},
        )

    @staticmethod
    def extract_output_data(result: Any) -> Any:
        for key in ("output", "data", "output_data", "result"):
            if isinstance(result, dict) and key in result:
                return result[key]
            if hasattr(result, key):
                return getattr(result, key)
        return result

    @staticmethod
    def make_tri_provider_tool(
        pipeline: TriProviderPipeline,
    ) -> Callable[[str, list[str] | None, str], dict[str, Any]]:
        def _tool(
            scenario: str,
            evidence_documents: list[str] | None = None,
            mode: str = "dry",
        ) -> dict[str, Any]:
            report = pipeline.run(
                scenario=scenario,
                evidence_documents=tuple(evidence_documents or ()),
                mode="live" if mode == "live" else "dry",
            )
            return report.to_dict()

        return _tool
