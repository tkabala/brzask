"""Application logic shared by the CLI, the worker, the API and the MCP server.

Services take a `Session` and leave committing to the caller, except the
pipeline runner, which commits each step itself so a run is visible while it
is in progress.
"""
