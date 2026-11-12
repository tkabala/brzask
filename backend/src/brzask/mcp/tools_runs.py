"""Starting pipeline runs."""

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from brzask.db.models import RunKind
from brzask.mcp.server import McpDeps, current_identity, require_write


class StartedRun(BaseModel):
    run_id: str
    kind: RunKind
    dry_run: bool
    status: Literal["running"] = "running"


def register(server: MCPServer[Any], deps: McpDeps) -> None:
    @server.tool()
    def start_run(
        kind: Literal["digest", "review", "visited", "discovery"],
        dry_run: bool = True,
        force: bool = False,
    ) -> StartedRun:
        """Start a pipeline in the background and return its run ID; follow it with get_run.

        A dry run writes nothing but still calls paid APIs (a digest costs a few
        cents); a read token may start one. A real run, or `force` (build today's
        digest again), needs a write token.
        """
        if not dry_run or force:
            require_write()
        else:
            current_identity()
        run_id = deps.runs.start(RunKind(kind), dry_run=dry_run, force=force)
        return StartedRun(run_id=str(run_id), kind=RunKind(kind), dry_run=dry_run)
