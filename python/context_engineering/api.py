from __future__ import annotations

from typing import Literal

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


class PackRequest(BaseModel):
    items: list[ContextItem] = Field(default_factory=list)
    budget: Budget
    allow_compression: bool = True
    provider: TokenProvider = "heuristic"
    weights: ScoringWeightsModel | None = None
    redundancy_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


def create_app() -> FastAPI:
    configure_structlog()
    log = structlog.get_logger(__name__)

    app = FastAPI(title="Context Engineering API", version="0.1.0")

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

        return pack(
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

        return trace_pack(
            request.items,
            request.budget,
            allow_compression=request.allow_compression,
            provider=provider,
            weights=weights,
            redundancy_threshold=request.redundancy_threshold,
        )

    return app


app = create_app()
