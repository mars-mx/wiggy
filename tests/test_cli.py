"""Tests for the CLI."""

from click.testing import CliRunner

from wiggy import __version__
from wiggy.cli import main


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
    runner = CliRunner()
    result = runner.invoke(main, ["run"])
    assert result.exit_code == 0
    assert "wiggy loop" in result.output.lower()
