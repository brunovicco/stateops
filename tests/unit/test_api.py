"""HTTP boundary tests with an injected technology-neutral runtime."""

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from stateops.application.runtime_models import CheckpointView, RunResult
from stateops.domain.models import IncidentRecord
from stateops.entrypoints.api.app import create_app


class FakeRuntime:
    """Capture validated domain calls without starting Redis."""

    def __init__(self) -> None:
        self.incident: IncidentRecord | None = None

    async def start(self, incident_id: str, incident: IncidentRecord) -> RunResult:
        self.incident = incident
        return RunResult(
            values={"incident_id": incident_id, "phase": "waiting_approval"},
            interrupted=True,
            interrupts=({"action": {"id": "rollback"}},),
        )

    async def resume(self, incident_id: str, approval: Mapping[str, object]) -> RunResult:
        return RunResult(
            values={"incident_id": incident_id, "phase": "resolved", "approval": approval},
            interrupted=False,
            interrupts=(),
        )

    async def state(self, incident_id: str) -> Mapping[str, object]:
        return {"incident_id": incident_id, "phase": "waiting_approval"}

    async def history(self, incident_id: str) -> tuple[CheckpointView, ...]:
        return (
            CheckpointView(
                checkpoint_id="cp-1",
                phase="waiting_approval",
                next_nodes=("human_approval",),
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                source="loop",
                step=3,
            ),
        )

    async def replay(self, incident_id: str, checkpoint_id: str) -> RunResult:
        if checkpoint_id == "missing":
            raise KeyError(checkpoint_id)
        return RunResult({"incident_id": incident_id, "replayed": checkpoint_id}, False, ())

    async def fork(
        self, incident_id: str, checkpoint_id: str, selected_action_id: str
    ) -> RunResult:
        if selected_action_id == "invalid":
            raise ValueError("selected action is not a candidate in that checkpoint")
        return RunResult(
            {
                "incident_id": incident_id,
                "checkpoint_id": checkpoint_id,
                "selected_action_id": selected_action_id,
            },
            True,
            ({"action": {"id": selected_action_id}},),
        )

    async def stream_values(
        self, incident_id: str, incident: IncidentRecord
    ) -> AsyncIterator[Mapping[str, object]]:
        del incident
        yield {"incident_id": incident_id, "phase": "enriching"}
        yield {"incident_id": incident_id, "phase": "waiting_approval"}


def _payload() -> dict[str, object]:
    return {
        "incident_id": "INC-1",
        "service": "checkout-service",
        "error_rate_before": 0.2,
        "error_rate_after": 18.0,
        "deployment": "v2.31",
        "started_at": "2026-01-01T00:00:00Z",
    }


def test_api_drives_incident_approval_history_and_time_travel() -> None:
    runtime = FakeRuntime()
    with TestClient(create_app(runtime=runtime)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        created = client.post("/incidents", json=_payload())
        assert created.status_code == 202
        assert created.json()["interrupted"] is True
        assert runtime.incident is not None
        assert runtime.incident.started_at.tzinfo is not None

        assert client.get("/incidents/INC-1").json()["phase"] == "waiting_approval"
        approved = client.post(
            "/incidents/INC-1/approval",
            json={"decision": "approved", "action_id": "rollback", "comment": "ok"},
        )
        assert approved.json()["state"]["phase"] == "resolved"
        assert client.get("/incidents/INC-1/history").json()[0]["checkpoint_id"] == "cp-1"
        assert client.post("/incidents/INC-1/replay/cp-1").json()["state"]["replayed"] == "cp-1"
        assert client.post("/incidents/INC-1/replay/missing").status_code == 404

        forked = client.post(
            "/incidents/INC-1/fork",
            json={"checkpoint_id": "cp-1", "selected_action_id": "rollback"},
        )
        assert forked.json()["interrupted"] is True
        invalid = client.post(
            "/incidents/INC-1/fork",
            json={"checkpoint_id": "cp-1", "selected_action_id": "invalid"},
        )
        assert invalid.status_code == 422


def test_operator_console_is_local_packaged_and_csp_protected() -> None:
    with TestClient(create_app(runtime=FakeRuntime())) as client:
        page = client.get("/ui")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert page.headers["content-security-policy"].startswith("default-src 'none'")
        assert page.headers["x-content-type-options"] == "nosniff"
        assert "StateOps Control Room" in page.text
        assert '<script src="/ui/assets/app.js" defer></script>' in page.text

        stylesheet = client.get("/ui/assets/app.css")
        assert stylesheet.status_code == 200
        assert stylesheet.headers["content-type"].startswith("text/css")

        script = client.get("/ui/assets/app.js")
        assert script.status_code == 200
        assert "innerHTML" not in script.text
        assert "incidents/${encodeURIComponent(incidentId)}/approval" in script.text
        assert "URLSearchParams" in script.text


def test_api_validates_incidents_and_streams_v3_value_projection_as_sse() -> None:
    with TestClient(create_app(runtime=FakeRuntime())) as client:
        invalid = _payload()
        invalid["error_rate_after"] = 0.1
        assert client.post("/incidents", json=invalid).status_code == 422

        mismatch = client.post("/incidents/OTHER/events", json=_payload())
        assert mismatch.status_code == 422
        streamed = client.post("/incidents/INC-1/events", json=_payload())
        assert streamed.status_code == 200
        assert streamed.headers["content-type"].startswith("text/event-stream")
        assert "event: state" in streamed.text
        assert "waiting_approval" in streamed.text
