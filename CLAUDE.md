# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

All commands should be run using the `.venv` virtual environment:

```bash
# Install for development
uv venv
uv pip install -e ".[dev]"

# Run the CLI
.venv/bin/wiggy --help
.venv/bin/wiggy run
.venv/bin/wiggy preflight

# Testing
.venv/bin/pytest tests/                    # Run all tests
.venv/bin/pytest tests/test_engines.py     # Run specific test file
.venv/bin/pytest tests/test_engines.py::test_engine_dataclass  # Run single test

# Linting & Formatting
.venv/bin/ruff check src/
.venv/bin/ruff format src/

# Type Checking
.venv/bin/mypy src/
```

## Architecture

Wiggy is a CLI tool that provides a persistent iteration framework for AI-assisted coding, supporting multiple AI coding engines.

### Module Structure

- **cli.py** - Click-based command-line interface with `main`, `run`, and `preflight` commands
- **runner.py** - Engine resolution logic; auto-selects when single engine available, validates installation
- **console.py** - Shared Rich console instance for formatted output
- **config/preflight.py** - Environment validation (Docker daemon, available engines)
- **engines/** - Pluggable engine system:
  - **base.py** - `Engine` dataclass with `name`, `cli_command`, `install_info`, and `is_installed()` method
  - Individual engine modules (claude, cursor, opencode, codex, qwen, droid, copilot)
  - **__init__.py** - Registry with `ENGINES` tuple and helper functions: `get_available_engines()`, `get_missing_engines()`, `get_engine_by_name()`

### Engine Detection Pattern

Engines use `shutil.which()` to check if their CLI command exists in PATH. Each engine is a frozen dataclass with installation info URL.

## Testing Patterns

- Uses pytest with Click's `CliRunner` for CLI tests
- Mock `shutil.which` to test engine detection without actual installations
- Type hints required throughout (strict mypy enabled)
