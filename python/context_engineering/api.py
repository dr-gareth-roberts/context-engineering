from __future__ import annotations

import os
from typing import Literal

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .core import Budget, ContextItem, ContextPack, ContextTrace, ScoringWeights, pack, trace_pack
from .errors import BudgetExceededError, ContextEngineeringError, ValidationError
from .logging import configure_structlog

TokenProvider = Literal["heuristic", "openai", "anthropic"]


class ScoringWeightsModel(BaseModel):
    priority: float = 1.0
    recency: float = 0.7
    salience: float = 0.5
    relevance: float = 0.0
    cost: float = -0.3
    latency: float = -0.2
    relation_boost: float = 2.0

    def to_dataclass(self) -> ScoringWeights:
        return ScoringWeights(
            priority=self.priority,
            recency=self.recency,
            salience=self.salience,
            relevance=self.relevance,
            cost=self.cost,
            latency=self.latency,
            relation_boost=self.relation_boost,
        )


# Maximum number of items accepted in a single pack/trace request. Bounds the
# in-memory materialisation of the items array (Pydantic returns 422 if exceeded).
MAX_ITEMS = 10_000

# Maximum raw request body size in bytes. Enforced independently of item count so
# a few oversized items cannot exhaust memory. Overridable via env for tuning.
MAX_BODY_BYTES = int(os.environ.get("CE_API_MAX_BODY_BYTES", str(10 * 1024 * 1024)))


class PackRequest(BaseModel):
    items: list[ContextItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    budget: Budget
    allow_compression: bool = True
    provider: TokenProvider = "heuristic"
    weights: ScoringWeightsModel | None = None
    redundancy_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared body size exceeds ``max_body_bytes`` (413).

    Enforced independently of the per-item ``max_length`` bound so that a small
    number of very large items cannot exhaust memory before the handler runs.
    The check uses the ``Content-Length`` header only: we deliberately do NOT
    consume ``request.stream()`` here, because ``BaseHTTPMiddleware`` does not let
    a re-buffered body reach the downstream handler (it would arrive empty and
    every request would 422). A ``Transfer-Encoding: chunked`` request with no
    ``Content-Length`` bypasses this byte cap, but the item-count ``max_length``
    bound still limits the materialised array — the primary attack vector.
    """

    def __init__(self, app: object, max_body_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next: object) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                too_big = int(content_length) > self._max_body_bytes
            except ValueError:
                too_big = True
            if too_big:
                return self._too_large()
        return await call_next(request)  # type: ignore[misc]

    def _too_large(self) -> Response:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "REQUEST_TOO_LARGE",
                    "message": (
                        f"Request body exceeds the maximum of {self._max_body_bytes} bytes"
                    ),
                }
            },
        )


def create_app() -> FastAPI:
    configure_structlog()
    log = structlog.get_logger(__name__)

    app = FastAPI(title="Context Engineering API", version="0.1.0")
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=MAX_BODY_BYTES)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(ValidationError)
    async def handle_validation_error(_request: Request, exc: ValidationError) -> JSONResponse:
        details = [{"path": d.path, "message": d.message} for d in exc.details]
        return JSONResponse(
            status_code=400,
            content={
                "error": {"code": exc.code, "message": str(exc), "details": details},
            },
        )

    @app.exception_handler(BudgetExceededError)
    async def handle_budget_exceeded(_request: Request, exc: BudgetExceededError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(ContextEngineeringError)
    async def handle_ce_error(_request: Request, exc: ContextEngineeringError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.post("/api/v1/pack", response_model=ContextPack)
    async def pack_context(request: PackRequest) -> ContextPack:
        provider = None if request.provider == "heuristic" else request.provider
        weights = request.weights.to_dataclass() if request.weights else None

        log.info(
            "pack_requested",
            item_count=len(request.items),
            max_tokens=request.budget.max_tokens,
            provider=request.provider,
            allow_compression=request.allow_compression,
        )

        # pack() is synchronous and CPU-bound; offload to the threadpool so a
        # single heavy request cannot stall the event loop for all clients.
        return await run_in_threadpool(
            pack,
            request.items,
            request.budget,
            allow_compression=request.allow_compression,
            provider=provider,
            weights=weights,
            redundancy_threshold=request.redundancy_threshold,
        )

    @app.post("/api/v1/trace", response_model=ContextTrace)
    async def trace_context(request: PackRequest) -> ContextTrace:
        provider = None if request.provider == "heuristic" else request.provider
        weights = request.weights.to_dataclass() if request.weights else None

        log.info(
            "trace_requested",
            item_count=len(request.items),
            max_tokens=request.budget.max_tokens,
            provider=request.provider,
        )

        # trace_pack() is synchronous and CPU-bound; offload to the threadpool so a
        # single heavy request cannot stall the event loop for all clients.
        return await run_in_threadpool(
            trace_pack,
            request.items,
            request.budget,
            allow_compression=request.allow_compression,
            provider=provider,
            weights=weights,
            redundancy_threshold=request.redundancy_threshold,
        )

    return app


app = create_app()
