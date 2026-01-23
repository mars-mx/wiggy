"""Tests for preflight checks."""

from click.testing import CliRunner

from wiggy.cli import main


def test_preflight_help() -> None:
    """Test that the preflight command exists and has help."""
    runner = CliRunner()
    result = runner.invoke(main, ["preflight", "--help"])
    assert result.exit_code == 0
    assert "Validate environment" in result.output
