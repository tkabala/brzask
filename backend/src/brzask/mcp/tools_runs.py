"""Starting pipeline runs."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from brzask.config import get_settings
from brzask.db.models import RunKind
from brzask.mcp.errors import service_errors
from brzask.mcp.server import McpDeps, current_identity, require_write
from brzask.repositories import SourceRepository
from brzask.services.budget import check_budget
from brzask.services.replay import MAX_DAYS, MAX_EXCLUDED


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

    @server.tool()
    def start_replay(
        days: Annotated[int, Field(ge=1, le=MAX_DAYS)] = 14,
        exclude_source_ids: list[int] | None = None,
    ) -> StartedRun:
        """Choose the last `days` digests again, as set up now and without the given
        sources, and return the run ID; follow it with get_run.

        Checks a mute before proposing it: the run's stats compare opened picks
        with and without the sources (`current`, `candidate`), and `per_day.lost`
        names opened articles of the real digests that came from them. It writes
        nothing but calls the LLM two or three times per day on each side, about
        $0.10 for 14 days, counted towards the spending limits; any token may
        start one. A replay started while another runs is recorded as skipped.
        """
        current_identity()
        exclude = list(dict.fromkeys(exclude_source_ids or []))
        if len(exclude) > MAX_EXCLUDED:
            raise ToolError(f"leave out at most {MAX_EXCLUDED} sources at once")
        settings = get_settings()
        with deps.sessions.begin() as session, service_errors():
            found = SourceRepository(session).get_many(exclude)
            if missing := [i for i in exclude if i not in found]:
                raise ToolError(f"no source {missing[0]}")
            budget = check_budget(
                session, datetime.now(UTC), settings.budget, settings.scheduler.timezone
            )
        if budget is not None and budget.reason is not None:
            raise ToolError(budget.reason)
        run_id = deps.runs.start(
            RunKind.REPLAY, dry_run=True, force=False, pipeline=deps.replay(days, exclude)
        )
        return StartedRun(run_id=str(run_id), kind=RunKind.REPLAY, dry_run=True)
