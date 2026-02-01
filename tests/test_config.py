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
from wiggy.config.schema import (
    DEFAULT_CONFIG,
    OrchestratorConfig,
    WiggyConfig,
    resolve_orchestrator_config,
)
from wiggy.processes.base import ProcessSpec, ProcessStep


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

    def test_git_author_fields_default_none(self) -> None:
        """Test that git author fields default to None."""
        config = WiggyConfig()
        assert config.git_author_name is None
        assert config.git_author_email is None

    def test_git_author_roundtrip(self) -> None:
        """Test git author fields survive to_dict/from_dict roundtrip."""
        config = WiggyConfig(
            git_author_name="Test User",
            git_author_email="test@example.com",
        )
        data = config.to_dict()
        assert data["git_author_name"] == "Test User"
        assert data["git_author_email"] == "test@example.com"

        restored = WiggyConfig.from_dict(data)
        assert restored.git_author_name == "Test User"
        assert restored.git_author_email == "test@example.com"

    def test_git_author_merge(self) -> None:
        """Test git author fields merge with correct precedence."""
        base = WiggyConfig(
            git_author_name="Base User",
            git_author_email="base@example.com",
        )
        override = WiggyConfig(git_author_name="Override User")
        merged = base.merge(override)

        assert merged.git_author_name == "Override User"
        assert merged.git_author_email == "base@example.com"


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


class TestOrchestratorConfig:
    """Tests for OrchestratorConfig dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        cfg = OrchestratorConfig()
        assert cfg.enabled is True
        assert cfg.engine is None
        assert cfg.model == "opus"
        assert cfg.max_injections == 3
        assert cfg.image is None

    def test_from_dict_full(self) -> None:
        """Test from_dict with all fields specified."""
        data = {
            "enabled": False,
            "engine": "claude",
            "model": "sonnet",
            "max_injections": 5,
            "image": "custom:latest",
        }
        cfg = OrchestratorConfig.from_dict(data)
        assert cfg.enabled is False
        assert cfg.engine == "claude"
        assert cfg.model == "sonnet"
        assert cfg.max_injections == 5
        assert cfg.image == "custom:latest"

    def test_from_dict_partial_uses_defaults(self) -> None:
        """Test from_dict with partial data uses defaults."""
        cfg = OrchestratorConfig.from_dict({"enabled": False})
        assert cfg.enabled is False
        assert cfg.model == "opus"
        assert cfg.max_injections == 3

    def test_from_dict_empty_uses_defaults(self) -> None:
        """Test from_dict with empty dict uses all defaults."""
        cfg = OrchestratorConfig.from_dict({})
        assert cfg.enabled is True
        assert cfg.model == "opus"
        assert cfg.max_injections == 3

    def test_to_dict_roundtrip(self) -> None:
        """Test to_dict/from_dict roundtrip."""
        cfg = OrchestratorConfig(
            enabled=True, engine="claude", model="opus", max_injections=3
        )
        data = cfg.to_dict()
        restored = OrchestratorConfig.from_dict(data)
        assert restored == cfg

    def test_overlay_replaces_non_none_fields(self) -> None:
        """Test that overlay applies non-None fields from other."""
        base = OrchestratorConfig(engine="claude", model="opus", max_injections=3)
        override = OrchestratorConfig(engine="opencode", model="sonnet", max_injections=5)
        result = base.overlay(override)
        assert result.engine == "opencode"
        assert result.model == "sonnet"
        assert result.max_injections == 5

    def test_overlay_preserves_base_when_other_is_none(self) -> None:
        """Test that overlay keeps base fields when other has None."""
        base = OrchestratorConfig(engine="claude", model="opus", image="myimg:1")
        override = OrchestratorConfig(engine=None, model=None, image=None)
        result = base.overlay(override)
        assert result.engine == "claude"
        assert result.model == "opus"
        assert result.image == "myimg:1"


class TestOrchestratorInWiggyConfig:
    """Tests for orchestrator field in WiggyConfig."""

    def test_default_orchestrator(self) -> None:
        """Test WiggyConfig has default OrchestratorConfig."""
        cfg = WiggyConfig()
        assert cfg.orchestrator.enabled is True
        assert cfg.orchestrator.model == "opus"

    def test_from_dict_with_orchestrator(self) -> None:
        """Test WiggyConfig.from_dict parses orchestrator section."""
        data = {
            "engine": "claude",
            "orchestrator": {
                "enabled": True,
                "model": "opus",
                "max_injections": 5,
            },
        }
        cfg = WiggyConfig.from_dict(data)
        assert cfg.engine == "claude"
        assert cfg.orchestrator.enabled is True
        assert cfg.orchestrator.max_injections == 5

    def test_from_dict_without_orchestrator(self) -> None:
        """Test WiggyConfig.from_dict uses defaults when orchestrator missing."""
        cfg = WiggyConfig.from_dict({"engine": "claude"})
        assert cfg.orchestrator == OrchestratorConfig()

    def test_to_dict_includes_orchestrator(self) -> None:
        """Test WiggyConfig.to_dict includes orchestrator section."""
        cfg = WiggyConfig(engine="claude")
        data = cfg.to_dict()
        assert "orchestrator" in data
        assert data["orchestrator"]["enabled"] is True

    def test_merge_overlays_orchestrator(self) -> None:
        """Test WiggyConfig.merge overlays orchestrator config."""
        base = WiggyConfig(
            orchestrator=OrchestratorConfig(engine="claude", max_injections=3)
        )
        override = WiggyConfig(
            orchestrator=OrchestratorConfig(engine="opencode", max_injections=5)
        )
        merged = base.merge(override)
        assert merged.orchestrator.engine == "opencode"
        assert merged.orchestrator.max_injections == 5

    def test_parse_from_yaml(self, tmp_path: Path) -> None:
        """Test parsing orchestrator config from YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "engine: claude\n"
            "orchestrator:\n"
            "  enabled: true\n"
            "  engine: claude\n"
            "  model: opus\n"
            "  max_injections: 3\n"
        )
        data = load_yaml_config(config_file)
        assert data is not None
        cfg = WiggyConfig.from_dict(data)
        assert cfg.orchestrator.enabled is True
        assert cfg.orchestrator.engine == "claude"
        assert cfg.orchestrator.model == "opus"
        assert cfg.orchestrator.max_injections == 3


class TestResolveOrchestratorConfig:
    """Tests for resolve_orchestrator_config helper."""

    def test_global_only(self) -> None:
        """Test resolution with global config only (no process override)."""
        global_cfg = WiggyConfig(
            orchestrator=OrchestratorConfig(engine="claude", max_injections=3)
        )
        result = resolve_orchestrator_config(global_cfg, None)
        assert result.engine == "claude"
        assert result.max_injections == 3

    def test_process_override(self) -> None:
        """Test resolution with process-level override."""
        global_cfg = WiggyConfig(
            orchestrator=OrchestratorConfig(engine="claude", max_injections=3)
        )
        process_orch = OrchestratorConfig(engine="opencode", max_injections=5)
        result = resolve_orchestrator_config(global_cfg, process_orch)
        assert result.engine == "opencode"
        assert result.max_injections == 5

    def test_field_level_overlay(self) -> None:
        """Test that process override only replaces non-None fields."""
        global_cfg = WiggyConfig(
            orchestrator=OrchestratorConfig(
                engine="claude", model="opus", image="base:1"
            )
        )
        process_orch = OrchestratorConfig(engine=None, model="sonnet", image=None)
        result = resolve_orchestrator_config(global_cfg, process_orch)
        assert result.engine == "claude"  # preserved from global
        assert result.model == "sonnet"  # overridden by process
        assert result.image == "base:1"  # preserved from global


class TestProcessStepSkipOrchestrator:
    """Tests for skip_orchestrator on ProcessStep."""

    def test_default_false(self) -> None:
        """Test skip_orchestrator defaults to False."""
        step = ProcessStep(task="implement")
        assert step.skip_orchestrator is False

    def test_from_dict_skip_true(self) -> None:
        """Test parsing skip_orchestrator=true from dict."""
        step = ProcessStep.from_dict({"task": "format", "skip_orchestrator": True})
        assert step.skip_orchestrator is True

    def test_from_dict_skip_missing(self) -> None:
        """Test skip_orchestrator defaults when not in dict."""
        step = ProcessStep.from_dict({"task": "implement"})
        assert step.skip_orchestrator is False

    def test_to_dict_includes_skip_when_true(self) -> None:
        """Test to_dict includes skip_orchestrator when True."""
        step = ProcessStep(task="format", skip_orchestrator=True)
        data = step.to_dict()
        assert data["skip_orchestrator"] is True

    def test_to_dict_excludes_skip_when_false(self) -> None:
        """Test to_dict excludes skip_orchestrator when False."""
        step = ProcessStep(task="implement")
        data = step.to_dict()
        assert "skip_orchestrator" not in data


class TestProcessSpecOrchestrator:
    """Tests for orchestrator override on ProcessSpec."""

    def test_default_none(self) -> None:
        """Test orchestrator defaults to None on ProcessSpec."""
        spec = ProcessSpec(name="test", steps=())
        assert spec.orchestrator is None

    def test_from_dict_with_orchestrator(self) -> None:
        """Test parsing orchestrator from process.yaml dict."""
        data = {
            "name": "implement-feature",
            "orchestrator": {"enabled": True, "model": "opus", "max_injections": 5},
            "steps": [
                {"task": "analyse"},
                {"task": "implement"},
                {"task": "review"},
            ],
        }
        spec = ProcessSpec.from_dict(data)
        assert spec.orchestrator is not None
        assert spec.orchestrator.enabled is True
        assert spec.orchestrator.model == "opus"
        assert spec.orchestrator.max_injections == 5

    def test_from_dict_without_orchestrator(self) -> None:
        """Test ProcessSpec without orchestrator section."""
        data = {
            "name": "simple",
            "steps": [{"task": "run"}],
        }
        spec = ProcessSpec.from_dict(data)
        assert spec.orchestrator is None

    def test_to_dict_includes_orchestrator(self) -> None:
        """Test to_dict includes orchestrator when set."""
        spec = ProcessSpec(
            name="test",
            steps=(),
            orchestrator=OrchestratorConfig(enabled=True, max_injections=5),
        )
        data = spec.to_dict()
        assert "orchestrator" in data
        assert data["orchestrator"]["max_injections"] == 5

    def test_to_dict_excludes_orchestrator_when_none(self) -> None:
        """Test to_dict excludes orchestrator when None."""
        spec = ProcessSpec(name="test", steps=())
        data = spec.to_dict()
        assert "orchestrator" not in data
