"""FastAPI composition root for StateOps."""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict
from typing import Literal, cast

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from stateops import __version__
from stateops.adapters.clock import SystemClock
from stateops.adapters.incidents.synthetic_signals import SyntheticIncidentSignals
from stateops.adapters.llm.deterministic import DeterministicIncidentReasoner
from stateops.adapters.llm.governed_gateway import GovernedGatewayIncidentReasoner
from stateops.adapters.persistence.checkpointer import redis_checkpointer
from stateops.adapters.remediation.redis_executor import RedisSimulatedRemediationExecutor
from stateops.application.ports.reasoner import IncidentReasoner
from stateops.application.ports.runtime import IncidentRuntime
from stateops.application.runtime_models import RunResult
from stateops.entrypoints.api.schemas import ApprovalRequest, CreateIncidentRequest, ForkRequest
from stateops.graphs.incident_graph import build_incident_graph
from stateops.graphs.runtime import GraphIncidentRuntime


class StateOpsSettings(BaseSettings):
    """Process configuration with no provider credentials."""

    model_config = SettingsConfigDict(extra="ignore")

    redis_url: str = Field(
        default="redis://redis:6379/0",
        validation_alias="REDIS_URL",
    )
    reasoner: Literal["deterministic", "gateway"] = Field(
        default="deterministic", validation_alias="STATEOPS_REASONER"
    )
    llm_workload: str = Field(
        default="stateops.incident.reasoning", validation_alias="STATEOPS_LLM_WORKLOAD"
    )


def _runtime(app: FastAPI) -> IncidentRuntime:
    runtime = getattr(app.state, "incident_runtime", None)
    if runtime is None:
        raise RuntimeError("StateOps runtime is not initialized")
    return cast(IncidentRuntime, runtime)


def _run_response(result: RunResult) -> dict[str, object]:
    return {
        "state": jsonable_encoder(result.values),
        "interrupted": result.interrupted,
        "interrupts": jsonable_encoder(result.interrupts),
    }


def _lifespan(
    settings: StateOpsSettings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        clock = SystemClock()
        signals = SyntheticIncidentSignals()
        gateway_reasoner: GovernedGatewayIncidentReasoner | None = None
        if settings.reasoner == "gateway":
            gateway_reasoner = GovernedGatewayIncidentReasoner.from_env(
                workload=settings.llm_workload
            )
            reasoner: IncidentReasoner = gateway_reasoner
        else:
            reasoner = DeterministicIncidentReasoner()
        executor = RedisSimulatedRemediationExecutor(settings.redis_url, clock)
        try:
            async with redis_checkpointer(settings.redis_url) as checkpointer:
                await executor.setup()
                app.state.incident_runtime = GraphIncidentRuntime(
                    build_incident_graph(
                        reasoner=reasoner,
                        signals=signals,
                        executor=executor,
                        clock=clock,
                        checkpointer=checkpointer,
                    )
                )
                yield
        finally:
            await executor.aclose()
            if gateway_reasoner is not None:
                await gateway_reasoner.aclose()

    return lifespan


def create_app(
    *,
    runtime: IncidentRuntime | None = None,
    settings: StateOpsSettings | None = None,
) -> FastAPI:
    """Create an API with production composition or an injected test runtime."""
    resolved_settings = settings or StateOpsSettings()

    if runtime is None:
        lifespan = _lifespan(resolved_settings)
    else:

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            app.state.incident_runtime = runtime
            yield

    app = FastAPI(
        title="StateOps",
        version=__version__,
        description="Durable, replayable incident-response state machine.",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/incidents", status_code=202)
    async def create_incident(request: CreateIncidentRequest) -> dict[str, object]:
        result = await _runtime(app).start(request.incident_id, request.to_domain())
        return _run_response(result)

    @app.get("/incidents/{incident_id}")
    async def read_incident(incident_id: str) -> object:
        return jsonable_encoder(await _runtime(app).state(incident_id))

    @app.post("/incidents/{incident_id}/approval")
    async def approve_incident(incident_id: str, request: ApprovalRequest) -> dict[str, object]:
        result = await _runtime(app).resume(incident_id, request.model_dump())
        return _run_response(result)

    @app.get("/incidents/{incident_id}/history")
    async def incident_history(incident_id: str) -> object:
        history = await _runtime(app).history(incident_id)
        return jsonable_encoder([asdict(item) for item in history])

    @app.post("/incidents/{incident_id}/replay/{checkpoint_id}")
    async def replay_incident(incident_id: str, checkpoint_id: str) -> dict[str, object]:
        try:
            result = await _runtime(app).replay(incident_id, checkpoint_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="checkpoint not found") from exc
        return _run_response(result)

    @app.post("/incidents/{incident_id}/fork")
    async def fork_incident(incident_id: str, request: ForkRequest) -> dict[str, object]:
        try:
            result = await _runtime(app).fork(
                incident_id, request.checkpoint_id, request.selected_action_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="checkpoint not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _run_response(result)

    @app.post("/incidents/{incident_id}/events")
    async def stream_incident(
        incident_id: str, request: CreateIncidentRequest
    ) -> StreamingResponse:
        if incident_id != request.incident_id:
            raise HTTPException(status_code=422, detail="path and payload incident IDs differ")

        async def events() -> AsyncIterator[str]:
            async for values in _runtime(app).stream_values(incident_id, request.to_domain()):
                encoded = jsonable_encoder(values)
                yield f"event: state\ndata: {json.dumps(encoded, separators=(',', ':'))}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


app = create_app()
