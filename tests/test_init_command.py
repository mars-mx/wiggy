"""Tests for the wiggy init command."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from wiggy.cli import main


class TestInitCommand:
    """Tests for the init command."""

    def test_init_help(self) -> None:
        """Test that init --help shows help."""
        runner = CliRunner()
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "configuration" in result.output.lower()

    def test_init_show_displays_config(self, tmp_path: Path) -> None:
        """Test that init --show displays current configuration."""
        home_config = tmp_path / ".wiggy" / "config.yaml"
        local_config = tmp_path / "project" / ".wiggy" / "config.yaml"

        home_config.parent.mkdir(parents=True)
        home_config.write_text("engine: claude\n")

        with (
            patch(
                "wiggy.config.loader.get_home_config_path", return_value=home_config
            ),
            patch(
                "wiggy.config.loader.get_local_config_path", return_value=local_config
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["init", "--show"])
            assert result.exit_code == 0
            assert "Current Effective Configuration" in result.output

    def test_init_first_time_prompts_wizard(self, tmp_path: Path) -> None:
        """Test that init prompts for wizard when no home config exists."""
        home_config = tmp_path / ".wiggy" / "config.yaml"
        local_config = tmp_path / "project" / ".wiggy" / "config.yaml"

        with (
            patch(
                "wiggy.cli.get_home_config_path", return_value=home_config
            ),
            patch(
                "wiggy.cli.home_config_exists", return_value=False
            ),
        ):
            runner = CliRunner()
            # Answer 'n' to skip wizard
            result = runner.invoke(main, ["init"], input="n\n")
            assert result.exit_code == 0
            assert "first time" in result.output.lower()

    def test_init_existing_home_prompts_local(self, tmp_path: Path) -> None:
        """Test that init prompts for local config when home config exists."""
        home_config = tmp_path / ".wiggy" / "config.yaml"
        local_config = tmp_path / "project" / ".wiggy" / "config.yaml"

        home_config.parent.mkdir(parents=True)
        home_config.write_text("engine: claude\n")

        with (
            patch(
                "wiggy.cli.get_home_config_path", return_value=home_config
            ),
            patch(
                "wiggy.cli.home_config_exists", return_value=True
            ),
            patch(
                "wiggy.cli.local_config_exists", return_value=False
            ),
            patch(
                "wiggy.config.loader.get_home_config_path", return_value=home_config
            ),
            patch(
                "wiggy.config.loader.get_local_config_path", return_value=local_config
            ),
        ):
            runner = CliRunner()
            # Answer 'n' to skip local override
            result = runner.invoke(main, ["init"], input="n\n")
            assert result.exit_code == 0
            assert "Global configuration found" in result.output
