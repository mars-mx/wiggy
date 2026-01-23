"""Tests for engine detection."""

from unittest.mock import patch

from wiggy.engines import ENGINES, Engine, get_available_engines, get_missing_engines


def test_engine_dataclass() -> None:
    """Test Engine dataclass creation."""
    engine = Engine(
        name="Test Engine",
        cli_command="test-cmd",
        install_info="test install info",
    )
    assert engine.name == "Test Engine"
    assert engine.cli_command == "test-cmd"
    assert engine.install_info == "test install info"


def test_engine_is_installed_true() -> None:
    """Test is_installed returns True when command exists."""
    engine = Engine(name="Python", cli_command="python", install_info="test")
    # python should always be available in test environment
    assert engine.is_installed() is True


def test_engine_is_installed_false() -> None:
    """Test is_installed returns False when command doesn't exist."""
    engine = Engine(
        name="Test",
        cli_command="nonexistent-command-xyz-12345",
        install_info="test",
    )
    assert engine.is_installed() is False


def test_engines_registry_not_empty() -> None:
    """Test that ENGINES registry contains entries."""
    assert len(ENGINES) == 7


def test_all_engines_have_required_fields() -> None:
    """Test all engines have valid data."""
    for engine in ENGINES:
        assert engine.name, "Engine must have a name"
        assert engine.cli_command, "Engine must have a CLI command"
        assert engine.install_info, "Engine must have install info"


def test_engines_registry_contains_expected_engines() -> None:
    """Test that all expected engines are in the registry."""
    engine_names = {e.name for e in ENGINES}
    expected = {
        "Claude Code",
        "OpenCode",
        "Cursor",
        "Codex",
        "Qwen-Code",
        "Factory Droid",
        "GitHub Copilot",
    }
    assert engine_names == expected


@patch("wiggy.engines.base.shutil.which")
def test_get_available_engines(mock_which) -> None:
    """Test get_available_engines filters correctly."""
    # Simulate only 'claude' being installed
    mock_which.side_effect = lambda cmd: "/usr/bin/claude" if cmd == "claude" else None

    available = get_available_engines()
    assert len(available) == 1
    assert available[0].cli_command == "claude"


@patch("wiggy.engines.base.shutil.which")
def test_get_missing_engines(mock_which) -> None:
    """Test get_missing_engines filters correctly."""
    # Simulate only 'claude' being installed
    mock_which.side_effect = lambda cmd: "/usr/bin/claude" if cmd == "claude" else None

    missing = get_missing_engines()
    assert len(missing) == 6
    assert all(e.cli_command != "claude" for e in missing)


@patch("wiggy.engines.base.shutil.which")
def test_get_available_engines_none_installed(mock_which) -> None:
    """Test get_available_engines when no engines installed."""
    mock_which.return_value = None

    available = get_available_engines()
    assert len(available) == 0


@patch("wiggy.engines.base.shutil.which")
def test_get_available_engines_all_installed(mock_which) -> None:
    """Test get_available_engines when all engines installed."""
    mock_which.return_value = "/usr/bin/some-command"

    available = get_available_engines()
    assert len(available) == 7
