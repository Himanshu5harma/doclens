"""An optional single-release LangGraph wrapper around the direct RAG functions."""

import json
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from doclens.answers import AnswerResult, PreparedQuestion, _safe_input, answer_question, prepare_question, validate_answer
from doclens.generation import Completion, GenerationConfig, GenerationError, Generator, OpenRouterClient


@dataclass(frozen=True)
class WorkflowError:
    stage: str
    kind: str
    message: str


class WorkflowState(TypedDict):
    question: str
    product: str
    version: str
    inspect_only: bool
    prepared: NotRequired[PreparedQuestion]
    completion: NotRequired[Completion]
    result: NotRequired[AnswerResult]
    error: NotRequired[WorkflowError]


def _redact(text: str) -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        text = text.replace(key, "[REDACTED]")
    return re.sub(r"sk-or-v1-[A-Za-z0-9_-]+", "[REDACTED]", text)


def _failure(stage: str, error: Exception) -> dict:
    if isinstance(error, GenerationError):
        kind, message = error.kind, str(error)
    elif stage == "generate":
        # Third-party/injected clients might expose request headers in errors.
        kind, message = "transport", "Generation client failed; no automatic retry was made."
    else:
        kind, message = ("input" if isinstance(error, ValueError) else "index"), str(error)
    return {"error": WorkflowError(stage, _redact(kind), _redact(message))}


def _after_prepare(state: WorkflowState) -> Literal["generate", "insufficient", "__end__"]:
    if "error" in state or state["inspect_only"]:
        return "__end__"
    return "generate" if state["prepared"].evidence else "insufficient"


def _after_generate(state: WorkflowState) -> Literal["validate", "__end__"]:
    return "__end__" if "error" in state else "validate"


def _build_graph(*, index: Path, root: Path, config: GenerationConfig,
                 client: Generator | None, encoder, preparer: Callable | None, top_k: int):
    # Keep the base CLI and direct pipeline usable without the optional extra.
    try:
        from langgraph.graph import END, START, StateGraph
        from langgraph.types import RetryPolicy
    except ModuleNotFoundError:
        raise ValueError("Graph workflow requires the optional dependencies: uv sync --extra retrieval --extra graph") from None

    prepare = prepare_question if preparer is None else preparer

    def prepare_node(state: WorkflowState) -> dict:
        try:
            prepared = prepare(index, state["question"], version=state["version"],
                               product=state["product"], root=root, config=config,
                               top_k=top_k, encoder=encoder)
            _safe_input(json.dumps(asdict(prepared), ensure_ascii=False))
            return {"prepared": prepared}
        except (OSError, ValueError, sqlite3.Error) as error:
            return _failure("prepare", error)

    def generate_node(state: WorkflowState) -> dict:
        try:
            generator = OpenRouterClient() if client is None else client
            completion = generator.complete(state["prepared"].messages, config)
            _safe_input(json.dumps(asdict(completion), ensure_ascii=False))
            return {"completion": completion}
        except (OSError, ValueError) as error:
            return _failure("generate", error)

    def validate_node(state: WorkflowState) -> dict:
        try:
            return {"result": validate_answer(state["completion"], state["prepared"])}
        except (ValueError, TypeError) as error:
            return _failure("validate", error)

    def insufficient_node(state: WorkflowState) -> dict:
        # The route guarantees empty evidence; the existing function makes no API call.
        return {"result": answer_question(state["prepared"], config, client=client)}

    graph = StateGraph(WorkflowState)
    for name, node in (("prepare", prepare_node), ("generate", generate_node),
                       ("validate", validate_node), ("insufficient", insufficient_node)):
        graph.add_node(name, node, retry_policy=RetryPolicy(max_attempts=1))
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", _after_prepare)
    graph.add_conditional_edges("generate", _after_generate)
    graph.add_edge("validate", END)
    graph.add_edge("insufficient", END)
    return graph.compile()


def _trace_update(node: str, update: dict) -> dict:
    """Summarize state changes without emitting raw completions or prompt text."""
    event = {"node": node, "updated_fields": sorted(update)}
    if "prepared" in update:
        prepared = update["prepared"]
        event.update(passages=len(prepared.evidence), prompt_bytes=prepared.prompt_bytes,
                     prompt_sha256=prepared.prompt_sha256,
                     omitted_passages=len(prepared.omitted_chunk_ids))
    if "completion" in update:
        event["completion_received"] = True
    if "result" in update:
        result = update["result"]
        event.update(answer_status=result.status.value, citations=len(result.citations))
    if "error" in update:
        error = update["error"]
        event["error"] = {"stage": error.stage, "kind": error.kind, "message": error.message}
    return event


def run_workflow(index: Path, question: str, *, version: str, root: Path,
                 config: GenerationConfig, product: str = "python", top_k: int = 5,
                 inspect_only: bool = False, client: Generator | None = None,
                 encoder=None, preparer: Callable | None = None,
                 on_update: Callable[[dict], None] | None = None) -> WorkflowState:
    """Execute once, optionally streaming local summaries; never enable cloud tracing."""
    if type(inspect_only) is not bool:
        raise ValueError("inspect_only must be a boolean.")
    if not isinstance(question, str):
        raise ValueError("Question must be a string.")
    _safe_input(question)  # Block credentials before the question enters graph state.
    graph = _build_graph(index=index, root=root, config=config, client=client,
                         encoder=encoder, preparer=preparer, top_k=top_k)
    from langsmith import tracing_context

    initial: WorkflowState = {"question": question, "product": product, "version": version,
                              "inspect_only": inspect_only}
    final = initial
    # Explicitly override globally enabled LangSmith tracing. Local update events
    # are sufficient for this lesson; no checkpointer, remote callbacks, or cache.
    with tracing_context(enabled=False):
        for event in graph.stream(initial, config={"recursion_limit": 8, "callbacks": []},
                                  stream_mode=["updates", "values"], version="v2"):
            if event["type"] == "values":
                final = event["data"]
            elif event["type"] == "updates" and on_update is not None:
                for node, update in event["data"].items():
                    on_update(_trace_update(node, update))
    return final
