"""Small CLI for serving StateOps and inspecting the graph topology."""

import argparse
from collections.abc import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stateops")
    subcommands = parser.add_subparsers(dest="command", required=True)
    serve = subcommands.add_parser("serve", help="run the StateOps HTTP service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    subcommands.add_parser("graph", help="print the parent graph as Mermaid")
    return parser


def _print_graph() -> None:
    from stateops.adapters.clock import SystemClock
    from stateops.adapters.incidents.synthetic_signals import SyntheticIncidentSignals
    from stateops.adapters.llm.deterministic import DeterministicIncidentReasoner
    from stateops.adapters.remediation.simulated_executor import SimulatedRemediationExecutor
    from stateops.graphs.incident_graph import build_incident_graph

    clock = SystemClock()
    graph = build_incident_graph(
        reasoner=DeterministicIncidentReasoner(),
        signals=SyntheticIncidentSignals(),
        executor=SimulatedRemediationExecutor(clock),
        clock=clock,
        checkpointer=None,
    )
    print(graph.get_graph(xray=True).draw_mermaid())


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected StateOps command."""
    arguments = _parser().parse_args(argv)
    if arguments.command == "graph":
        _print_graph()
        return 0

    import uvicorn

    uvicorn.run(
        "stateops.entrypoints.api.app:app",
        host=str(arguments.host),
        port=int(arguments.port),
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
