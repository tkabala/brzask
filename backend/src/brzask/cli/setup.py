"""`brzask setup`: the secret files a deployment reads through `<NAME>_FILE`."""

import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from brzask.services import auth

# File names, not secrets: deploy/compose.yaml mounts each as its variable in lower case.
DB_PASSWORD = "db_password"  # noqa: S105
SESSION_SECRET = "auth_session_secret"  # noqa: S105
PASSWORD_HASH = "auth_password_hash"  # noqa: S105
LLM_API_KEY = "llm_api_key"
# For the optional crawler and search services of the compose file.
CRAWL4AI_API_TOKEN = "crawl4ai_api_token"  # noqa: S105
SEARXNG_SECRET = "searxng_secret"  # noqa: S105


def setup_command(
    directory: Annotated[
        Path, typer.Argument(help="Directory for the secret files; created when missing.")
    ] = Path("secrets"),
) -> None:
    """Write the secrets a deployment needs, one file each. Existing files are kept."""
    directory.mkdir(parents=True, exist_ok=True)
    # The files are readable by everyone, as the containers that mount them run
    # as their own users; the directory keeps other users of the host out.
    directory.chmod(0o700)
    _write(directory, DB_PASSWORD, lambda: secrets.token_urlsafe(32))
    _write(directory, SESSION_SECRET, lambda: secrets.token_urlsafe(48))
    _write(directory, PASSWORD_HASH, _password_hash)
    _write(directory, LLM_API_KEY, _llm_api_key)
    _write(directory, CRAWL4AI_API_TOKEN, lambda: secrets.token_urlsafe(32))
    _write(directory, SEARXNG_SECRET, lambda: secrets.token_urlsafe(32))
    if os.geteuid() == 0:
        # Run as root in a container: hand everything to whoever owns the
        # directory it lives in, the one mounted from the host.
        owner = directory.resolve().parent.stat()
        for path in (directory, *directory.iterdir()):
            os.chown(path, owner.st_uid, owner.st_gid)


def _password_hash() -> str:
    # Without a default, an empty answer is asked again.
    password: str = typer.prompt("Login password", hide_input=True, confirmation_prompt=True)
    return auth.hash_password(password)


def _llm_api_key() -> str:
    key: str = typer.prompt(
        "LLM API key (empty for a local server)", default="", show_default=False, hide_input=True
    )
    return key.strip()


def _write(directory: Path, name: str, value: Callable[[], str]) -> None:
    path = directory / name
    if path.exists():
        typer.echo(f"{path}: kept")
        return
    path.write_text(value() + "\n", encoding="utf-8")
    path.chmod(0o644)
    typer.echo(f"{path}: written")
