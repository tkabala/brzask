from typer.testing import CliRunner

from brzask import __version__
from brzask.cli import app

runner = CliRunner()


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"brzask {__version__}"
