"""Tests for configuration loading and merging."""

from pathlib import Path
from unittest.mock import patch

import yaml

from wiggy.config.loader import (
    get_home_config_path,
    get_local_config_path,
    home_config_exists,
    load_config,
    load_yaml_config,
    local_config_exists,
    save_config,
)
from wiggy.config.schema import DEFAULT_CONFIG, WiggyConfig


class TestWiggyConfig:
    """Tests for WiggyConfig dataclass."""

    def test_default_config_values(self) -> None:
        """Test that DEFAULT_CONFIG has expected values."""
        assert DEFAULT_CONFIG.executor == "docker"
        assert DEFAULT_CONFIG.parallel == 1
        assert DEFAULT_CONFIG.push is True
        assert DEFAULT_CONFIG.pr is True
        assert DEFAULT_CONFIG.remote == "origin"
        assert DEFAULT_CONFIG.keep_worktree is False

    def test_merge_prefers_other_values(self) -> None:
        """Test that merge prefers values from 'other' when set."""
        base = WiggyConfig(engine="claude", parallel=1)
        override = WiggyConfig(engine="opencode", parallel=4)
        merged = base.merge(override)

        assert merged.engine == "opencode"
        assert merged.parallel == 4

    def test_merge_preserves_base_when_other_is_none(self) -> None:
        """Test that merge preserves base values when other is None."""
        base = WiggyConfig(engine="claude", model="opus")
        override = WiggyConfig(engine="opencode")  # model not set (None)
        merged = base.merge(override)

        assert merged.engine == "opencode"
        assert merged.model == "opus"

    def test_merge_returns_new_instance(self) -> None:
        """Test that merge returns a new instance, not mutating originals."""
        base = WiggyConfig(engine="claude")
        override = WiggyConfig(parallel=4)
        merged = base.merge(override)

        assert merged is not base
        assert merged is not override
        assert base.parallel is None
        assert override.engine is None

    def test_to_dict_excludes_none(self) -> None:
        """Test that to_dict excludes None values."""
        config = WiggyConfig(engine="claude", model=None, parallel=4)
        data = config.to_dict()

        assert "engine" in data
        assert "parallel" in data
        assert "model" not in data
        assert data["engine"] == "claude"
        assert data["parallel"] == 4

    def test_from_dict_creates_config(self) -> None:
        """Test that from_dict creates a WiggyConfig from a dictionary."""
        data = {"engine": "claude", "parallel": 4, "push": True}
        config = WiggyConfig.from_dict(data)

        assert config.engine == "claude"
        assert config.parallel == 4
        assert config.push is True
        assert config.model is None  # Not in data

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """Test that from_dict ignores unknown keys."""
        data = {"engine": "claude", "unknown_key": "value"}
        config = WiggyConfig.from_dict(data)

        assert config.engine == "claude"
        assert not hasattr(config, "unknown_key")

    def test_from_dict_coerces_types(self) -> None:
        """Test that from_dict coerces types appropriately."""
        data = {"parallel": "4", "push": 1}  # String and int that should be coerced
        config = WiggyConfig.from_dict(data)

        assert config.parallel == 4
        assert config.push is True


class TestConfigPaths:
    """Tests for config path functions."""

    def test_get_home_config_path(self) -> None:
        """Test that home config path is in ~/.wiggy/."""
        path = get_home_config_path()
        assert path.name == "config.yaml"
        assert path.parent.name == ".wiggy"
        assert path.parent.parent == Path.home()

    def test_get_local_config_path(self, tmp_path: Path) -> None:
        """Test that local config path is in ./.wiggy/."""
        with patch("wiggy.config.loader.Path.cwd", return_value=tmp_path):
            path = get_local_config_path()
            assert path.name == "config.yaml"
            assert path.parent.name == ".wiggy"
            assert path.parent.parent == tmp_path


class TestConfigLoading:
    """Tests for config file loading."""

    def test_load_yaml_config_returns_dict(self, tmp_path: Path) -> None:
        """Test that load_yaml_config returns a dictionary."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("engine: claude\nparallel: 4\n")

        data = load_yaml_config(config_file)
        assert data == {"engine": "claude", "parallel": 4}

    def test_load_yaml_config_returns_none_for_missing_file(
        self, tmp_path: Path
    ) -> None:
        """Test that load_yaml_config returns None for missing file."""
        config_file = tmp_path / "nonexistent.yaml"
        assert load_yaml_config(config_file) is None

    def test_load_yaml_config_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        """Test that load_yaml_config returns None for empty file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        assert load_yaml_config(config_file) is None

    def test_load_yaml_config_returns_none_for_invalid_yaml(
        self, tmp_path: Path
    ) -> None:
        """Test that load_yaml_config returns None for invalid YAML."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: content: [")

        assert load_yaml_config(config_file) is None

    def test_home_config_exists_returns_true(self, tmp_path: Path) -> None:
        """Test home_config_exists returns True when file exists."""
        config_file = tmp_path / ".wiggy" / "config.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("engine: claude\n")

        with patch(
            "wiggy.config.loader.get_home_config_path", return_value=config_file
        ):
            assert home_config_exists() is True

    def test_home_config_exists_returns_false(self, tmp_path: Path) -> None:
        """Test home_config_exists returns False when file doesn't exist."""
        config_file = tmp_path / ".wiggy" / "config.yaml"

        with patch(
            "wiggy.config.loader.get_home_config_path", return_value=config_file
        ):
            assert home_config_exists() is False

    def test_local_config_exists_returns_true(self, tmp_path: Path) -> None:
        """Test local_config_exists returns True when file exists."""
        config_file = tmp_path / ".wiggy" / "config.yaml"
        config_file.parent.mkdir(parents=True)
        config_file.write_text("parallel: 4\n")

        with patch(
            "wiggy.config.loader.get_local_config_path", return_value=config_file
        ):
            assert local_config_exists() is True


class TestConfigMerging:
    """Tests for config loading and merging."""

    def test_load_config_uses_defaults_when_no_files(self, tmp_path: Path) -> None:
        """Test that load_config uses defaults when no config files exist."""
        home_config = tmp_path / "home" / ".wiggy" / "config.yaml"
        local_config = tmp_path / "local" / ".wiggy" / "config.yaml"

        with (
            patch("wiggy.config.loader.get_home_config_path", return_value=home_config),
            patch(
                "wiggy.config.loader.get_local_config_path", return_value=local_config
            ),
        ):
            config = load_config()

            # Should have default values
            assert config.executor == "docker"
            assert config.parallel == 1
            assert config.push is True

    def test_load_config_applies_home_config(self, tmp_path: Path) -> None:
        """Test that load_config applies home config values."""
        home_config = tmp_path / "home" / ".wiggy" / "config.yaml"
        local_config = tmp_path / "local" / ".wiggy" / "config.yaml"

        home_config.parent.mkdir(parents=True)
        home_config.write_text("engine: claude\nparallel: 2\n")

        with (
            patch("wiggy.config.loader.get_home_config_path", return_value=home_config),
            patch(
                "wiggy.config.loader.get_local_config_path", return_value=local_config
            ),
        ):
            config = load_config()

            assert config.engine == "claude"
            assert config.parallel == 2
            # Default values still apply
            assert config.executor == "docker"

    def test_load_config_local_overrides_home(self, tmp_path: Path) -> None:
        """Test that local config overrides home config values."""
        home_config = tmp_path / "home" / ".wiggy" / "config.yaml"
        local_config = tmp_path / "local" / ".wiggy" / "config.yaml"

        home_config.parent.mkdir(parents=True)
        home_config.write_text("engine: claude\nparallel: 2\n")

        local_config.parent.mkdir(parents=True)
        local_config.write_text("parallel: 8\n")  # Override parallel only

        with (
            patch("wiggy.config.loader.get_home_config_path", return_value=home_config),
            patch(
                "wiggy.config.loader.get_local_config_path", return_value=local_config
            ),
        ):
            config = load_config()

            # Home value preserved
            assert config.engine == "claude"
            # Local override applied
            assert config.parallel == 8


class TestConfigSaving:
    """Tests for config file saving."""

    def test_save_config_creates_file(self, tmp_path: Path) -> None:
        """Test that save_config creates the config file."""
        config_file = tmp_path / ".wiggy" / "config.yaml"
        config = WiggyConfig(engine="claude", parallel=4)

        save_config(config, config_file)

        assert config_file.exists()
        with config_file.open() as f:
            data = yaml.safe_load(f)
        assert data["engine"] == "claude"
        assert data["parallel"] == 4

    def test_save_config_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Test that save_config creates parent directories."""
        config_file = tmp_path / "deep" / "nested" / ".wiggy" / "config.yaml"
        config = WiggyConfig(engine="claude")

        save_config(config, config_file)

        assert config_file.exists()

    def test_save_config_excludes_none_values(self, tmp_path: Path) -> None:
        """Test that save_config excludes None values from the file."""
        config_file = tmp_path / "config.yaml"
        config = WiggyConfig(engine="claude", model=None)

        save_config(config, config_file)

        with config_file.open() as f:
            data = yaml.safe_load(f)
        assert "engine" in data
        assert "model" not in data
