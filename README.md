# wiggy

A highly opinionated Ralph Wiggum loop AI software development CLI for parallel task execution.

## Vision

Wiggy enables working on multiple tasks in parallel by orchestrating AI coding engines. For each task, Wiggy will:

1. **Spec the task** - Define clear requirements and acceptance criteria
2. **Create GitHub Issue** - Track the task in your repository
3. **Create PRD** - Generate a detailed Product Requirements Document
4. **Create GitHub Pull Request** - Open a PR with the PRD as description
5. **Create Git Worktree** - Isolated working directory from current repository
6. **Mount in Executor** - Attach worktree to Docker container or shell executor
7. **Execute the task** - AI engine works autonomously on the implementation
8. **Push for review** - Completed work pushed to GitHub for human review

## Installation

```bash
# Using uv (recommended)
uv pip install wiggy

# Using pip
pip install wiggy
```

For development:

```bash
uv venv
uv pip install -e ".[dev]"
```

## Quick Start

```bash
# Check environment is ready
wiggy preflight

# Run with auto-detected engine
wiggy run "Add user authentication"

# Run with specific engine
wiggy run -e claude "Implement dark mode"

# Run 3 tasks in parallel
wiggy run -p 3 "Fix login bug"
```

## CLI Commands

### `wiggy run`

Execute the main wiggy iteration loop.

```bash
wiggy run [OPTIONS] [PROMPT]
```

**Arguments:**
- `PROMPT` - Initial prompt/task description to pass to the engine

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--engine` | `-e` | AI engine to use (auto-detected if only one installed) |
| `--executor` | `-x` | Execution backend: `docker` (default) or `shell` |
| `--image` | `-i` | Docker image override (docker executor only) |
| `--parallel` | `-p` | Number of parallel executor instances (default: 1) |
| `--model` | `-m` | Model override passed to engine CLI |

**Examples:**

```bash
# Basic usage with prompt
wiggy run "Refactor the authentication module"

# Specify engine and model
wiggy run -e claude -m claude-sonnet-4-20250514 "Add unit tests"

# Run 5 parallel executors with custom Docker image
wiggy run -p 5 -i my-custom-image:latest "Fix all linting errors"

# Use shell executor instead of Docker
wiggy run -x shell "Update documentation"
```

### `wiggy preflight`

Validate environment readiness before running tasks.

```bash
wiggy preflight
```

**Checks performed:**
- Docker daemon connectivity and version
- Installed AI engines detection

### `wiggy --version`

Display CLI version.

### `wiggy --help`

Show help text.

## Supported Engines

Wiggy supports multiple AI coding engines. Only one needs to be installed.

| Engine | CLI Command | Status |
|--------|-------------|--------|
| Claude Code | `claude` | Full support with Docker image |
| OpenCode | `opencode` | Detection only |
| Cursor | `agent` | Detection only |
| Codex | `codex` | Detection only |
| Qwen-Code | `qwen` | Detection only |
| Factory Droid | `droid` | Detection only |
| GitHub Copilot | `copilot` | Detection only |

## Executors

### Docker Executor (default)

Runs engines in isolated Docker containers with:
- Automatic image pulling
- Credential mounting (read-only)
- Environment variable injection (`ANTHROPIC_API_KEY`)
- Real-time log streaming
- Session logging to `.wiggy/logs/`

### Shell Executor

Runs engines directly in a subprocess (work in progress).

## Architecture

```
src/wiggy/
├── cli.py           # Click-based CLI interface
├── runner.py        # Engine resolution & validation
├── monitor.py       # Real-time Rich Live display
├── console.py       # Shared Rich console
├── engines/         # Pluggable engine system
│   ├── base.py      # Engine dataclass
│   └── *.py         # Individual engine definitions
├── executors/       # Execution backends
│   ├── base.py      # Abstract Executor class
│   ├── docker.py    # Docker container executor
│   └── shell.py     # Shell executor (WIP)
├── parsers/         # Output parsing system
│   ├── base.py      # Abstract Parser class
│   ├── claude.py    # Claude stream-json parser
│   └── raw.py       # Raw passthrough parser
└── config/          # Configuration & validation
    ├── init.py      # .wiggy directory setup
    └── preflight.py # Environment checks
```

## Session Logs

All raw executor output is saved to `.wiggy/logs/` with timestamped session IDs:

```
.wiggy/logs/20260123_231412_exec1.log
.wiggy/logs/20260123_231412_exec2.log
```

## Development

```bash
# Run tests
.venv/bin/pytest tests/

# Linting
.venv/bin/ruff check src/
.venv/bin/ruff format src/

# Type checking
.venv/bin/mypy src/
```

## License

MIT
