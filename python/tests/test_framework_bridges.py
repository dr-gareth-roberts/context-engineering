from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from context_framework import DeepAgentsBridge, LangGraphBridge, PydanticAIBridge


class _Ranked:
    def __init__(self, action: str, score: float, source: str) -> None:
        self.action = action
        self.score = score
        self.source = source
        self.rationale = "ranked by confidence"
        self.perplexity = 1.23


class _Report:
    def __init__(self, scenario: str, mode: str) -> None:
        self.final_plan = f"plan for {scenario} ({mode})"
        self.ranked_actions = (
            _Ranked("isolate host", 0.91, "cerebras"),
            _Ranked("revoke token", 0.88, "anthropic"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "final_plan": self.final_plan,
            "ranked_actions": [
                {
                    "action": row.action,
                    "score": row.score,
                    "source": row.source,
                }
                for row in self.ranked_actions
            ],
        }


class _Pipeline:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        *,
        scenario: str,
        evidence_documents=(),
        mode: str = "dry",
        metadata: dict[str, str] | None = None,
    ) -> _Report:
        self.calls.append(
            {
                "scenario": scenario,
                "evidence_documents": tuple(evidence_documents),
                "mode": mode,
                "metadata": dict(metadata or {}),
            }
        )
        return _Report(scenario, mode)


class FrameworkBridgeTests(unittest.TestCase):
    def test_langgraph_compile_invoke_stream(self) -> None:
        class _Compiled:
            def __init__(self) -> None:
                self.invocations: list[tuple[dict[str, object], dict[str, object] | None]] = []

            def invoke(self, state, config=None):
                self.invocations.append((state, config))
                return {"ok": True, "state": state}

            def stream(self, state, **kwargs):
                yield {"state": state, "kwargs": kwargs}

        class _Graph:
            def __init__(self) -> None:
                self.compiled = _Compiled()

            def compile(self, **kwargs):
                self.compile_kwargs = kwargs
                return self.compiled

        graph = _Graph()
        compiled = LangGraphBridge.compile_graph(graph, checkpoint="sqlite")
        result = LangGraphBridge.invoke(compiled, {"x": 1}, config={"thread_id": "a"})
        stream = list(
            LangGraphBridge.stream(
                compiled,
                {"x": 2},
                config={"thread_id": "b"},
                stream_mode="updates",
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(stream[0]["kwargs"]["stream_mode"], "updates")

    def test_langgraph_tri_provider_node(self) -> None:
        pipeline = _Pipeline()
        node = LangGraphBridge.make_tri_provider_node(pipeline)

        output = node(
            {
                "scenario": "critical incident",
                "evidence_documents": ["e1", "e2"],
                "mode": "live",
                "metadata": {"run_id": "abc"},
            }
        )

        self.assertIn("tri_provider_report", output)
        self.assertIn("tri_provider_ranked_actions", output)
        self.assertEqual(pipeline.calls[0]["mode"], "live")

    def test_deepagents_create_agent_with_modern_factory(self) -> None:
        module = types.ModuleType("deepagents")
        module.create_deep_agent = lambda *args, **kwargs: {
            "args": args,
            "kwargs": kwargs,
        }

        with patch.dict(sys.modules, {"deepagents": module}):
            agent = DeepAgentsBridge.create_agent("model", tools=["a"])

        self.assertEqual(agent["args"][0], "model")
        self.assertEqual(agent["kwargs"]["tools"], ["a"])

    def test_deepagents_run_prefers_run_method(self) -> None:
        class _Agent:
            def run(self, task: str, **kwargs):
                return {"task": task, "kwargs": kwargs}

        result = DeepAgentsBridge.run(_Agent(), "stabilize incident", trace=True)
        self.assertEqual(result.metadata["method"], "run")
        self.assertEqual(result.output["task"], "stabilize incident")

    def test_deepagents_run_falls_back_to_invoke_and_ainvoke(self) -> None:
        class _InvokeAgent:
            def invoke(self, payload, **kwargs):
                return {"payload": payload, "kwargs": kwargs}

        class _AInvokeAgent:
            async def ainvoke(self, payload, **kwargs):
                return {"payload": payload, "kwargs": kwargs}

        invoke_result = DeepAgentsBridge.run(_InvokeAgent(), "check routing")
        ainvoke_result = DeepAgentsBridge.run(_AInvokeAgent(), "check routing")

        self.assertEqual(invoke_result.metadata["method"], "invoke")
        self.assertEqual(ainvoke_result.metadata["method"], "ainvoke")
        self.assertEqual(
            invoke_result.output["payload"]["messages"][0]["content"],
            "check routing",
        )

    def test_deepagents_run_requires_supported_method(self) -> None:
        with self.assertRaises(TypeError):
            DeepAgentsBridge.run(object(), "no methods")

    def test_deepagents_tri_provider_tool(self) -> None:
        pipeline = _Pipeline()
        tool = DeepAgentsBridge.make_tri_provider_tool(pipeline)
        output = tool("port disruption", ["lane delay"], "dry")

        self.assertIn("final_plan", output)
        self.assertEqual(pipeline.calls[0]["scenario"], "port disruption")

    def test_pydantic_ai_create_agent(self) -> None:
        class _Agent:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        module = types.ModuleType("pydantic_ai")
        module.Agent = _Agent

        with patch.dict(sys.modules, {"pydantic_ai": module}):
            agent = PydanticAIBridge.create_agent(
                "openai:gpt-4o-mini",
                system_prompt="Be concise",
                output_type=dict,
            )

        self.assertEqual(agent.args[0], "openai:gpt-4o-mini")
        self.assertEqual(agent.kwargs["system_prompt"], "Be concise")
        self.assertEqual(agent.kwargs["output_type"], dict)

    def test_pydantic_ai_run_sync_and_async_fallback(self) -> None:
        class _SyncAgent:
            def run_sync(self, prompt, **kwargs):
                return {"prompt": prompt, "kwargs": kwargs}

        class _AsyncAgent:
            async def run(self, prompt, **kwargs):
                return {"prompt": prompt, "kwargs": kwargs}

        sync_result = PydanticAIBridge.run_sync(_SyncAgent(), "summarize", trace=True)
        async_result = PydanticAIBridge.run_sync(_AsyncAgent(), "summarize", trace=True)

        self.assertEqual(sync_result.metadata["method"], "run_sync")
        self.assertEqual(async_result.metadata["method"], "run")
        self.assertEqual(sync_result.output["prompt"], "summarize")

    def test_pydantic_ai_extract_output_data(self) -> None:
        class _ResultObj:
            def __init__(self) -> None:
                self.output = {"answer": "ok"}

        extracted_from_obj = PydanticAIBridge.extract_output_data(_ResultObj())
        extracted_from_dict = PydanticAIBridge.extract_output_data({"data": {"answer": "ok"}})

        self.assertEqual(extracted_from_obj["answer"], "ok")
        self.assertEqual(extracted_from_dict["answer"], "ok")

    def test_pydantic_ai_tri_provider_tool(self) -> None:
        pipeline = _Pipeline()
        tool = PydanticAIBridge.make_tri_provider_tool(pipeline)
        output = tool("new regulation", ["control gap"], "dry")

        self.assertIn("final_plan", output)
        self.assertEqual(pipeline.calls[0]["scenario"], "new regulation")


if __name__ == "__main__":
    unittest.main()
