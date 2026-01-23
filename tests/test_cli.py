"""Tests for the CLI."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from wiggy import __version__
from wiggy.cli import main
from wiggy.engines.base import Engine


def test_cli_help() -> None:
    """Test that --help exits cleanly."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "wiggy" in result.output.lower()


def test_cli_version() -> None:
    """Test that --version shows the version."""
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_cli_run_command() -> None:
    """Test that run command works."""
    mock_engine = Engine(
        name="Test Engine",
        cli_command="test-cmd",
        install_info="https://example.com",
    )
    mock_executor = MagicMock()
    mock_executor.run.return_value = iter(["output line"])
    mock_executor.exit_code = 0

    with (
        patch("wiggy.cli.resolve_engine", return_value=mock_engine),
        patch("wiggy.executors.shell.ShellExecutor", return_value=mock_executor),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--executor", "shell"])
        assert result.exit_code == 0
        assert "wiggy loop" in result.output.lower()
