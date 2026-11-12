"""Tools that only read."""

from typing import Any

from mcp.server.mcpserver import MCPServer

from brzask.api.status import StatusOut, status_out
from brzask.mcp.errors import service_errors
from brzask.mcp.server import McpDeps


def register(server: MCPServer[Any], deps: McpDeps) -> None:
    sessions = deps.sessions

    @server.tool()
    def get_status() -> StatusOut:
        """Article and source counts, last digest day, pause and each pipeline's last run."""
        with sessions.begin() as session, service_errors():
            return status_out(session)
