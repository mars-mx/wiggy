# wiggy

A highly opinionated Ralph Wiggum loop AI software development CLI for parallel task execution.

Wiggy is a cracked software development intern that never rests, never sleeps, and never gets sick. The vision is to use him like an SD intern — point him at tasks, let him grind, and review his work when he's done.

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
| `--worktree` | | Path to existing git worktree to use |
| `--worktree-root` | | Root directory for auto-created worktrees |
| `--push/--no-push` | | Push to remote after execution (default: push) |
| `--pr/--no-pr` | | Create PR after execution (default: create PR) |
| `--remote` | | Git remote to push to (default: `origin`) |
| `--keep-worktree` | | Keep worktree after execution |
| `--resume-task` | | Resume a previous run by task_id (8 hex chars) |
| `--resume-branch` | | Resume a previous run by branch name |
| `--resume-session` | | Resume a previous run by engine session_id |
| `--continue-from` | | Create a child task linked to a parent task_id |

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

# Resume a previous task
wiggy run --resume-task abc12345

# Chain a follow-up task from a previous one
wiggy run --continue-from abc12345 "Now add tests for the feature"
```

### `wiggy preflight`

Validate environment readiness before running tasks.

```bash
wiggy preflight
```

**Checks performed:**
- Docker daemon connectivity and version
- Installed AI engines detection

### `wiggy init`

Initialize wiggy configuration interactively.

```bash
wiggy init            # Local project config (.wiggy/config.yaml)
wiggy init --global   # Global user config (~/.wiggy/config.yaml)
wiggy init --show     # Show current resolved config
```

### `wiggy history`

Show recent task execution history.

```bash
wiggy history          # Show last 10 tasks
wiggy history -n 25    # Show last 25 tasks
```

### `wiggy cleanup`

Clean up old task history records and log files.

```bash
wiggy cleanup                  # Delete tasks older than 30 days
wiggy cleanup --older-than 7   # Delete tasks older than 7 days
wiggy cleanup --dry-run        # Preview what would be deleted
```

### `wiggy task`

Manage and run named tasks.

```bash
wiggy task list                              # List available tasks
wiggy task run implement                     # Run a task by name
wiggy task run implement -e claude -p "..."  # With engine and prompt
wiggy task create                            # Create a new task via AI
wiggy task create --local                    # Create in local project tasks
```

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

## Tasks

Wiggy includes a named task system for common workflows. Each task is a YAML spec with a prompt template.

**Built-in tasks:**

| Task | Description |
|------|-------------|
| `analyse` | Analyse code or requirements |
| `create-task` | Create a new task definition via AI |
| `implement` | Implement a feature or change |
| `research` | Research a topic or codebase |
| `review` | Review code |
| `test` | Write or run tests |

Tasks are discovered from two locations:
- **Global:** `~/.wiggy/tasks/`
- **Local:** `.wiggy/tasks/` (project-specific)

Each task directory contains a `task.yaml` (metadata, tools, model) and a `prompt.md` (system prompt template).

## History & Resumption

Wiggy tracks every task execution in a local SQLite database (`.wiggy/history.db`), recording task ID, branch, engine, session ID, cost, tokens, duration, and exit status.

This enables resuming interrupted work:

```bash
# Resume by task ID
wiggy run --resume-task abc12345

# Resume by branch name
wiggy run --resume-branch feat/add-auth

# Resume by engine session ID
wiggy run --resume-session sess_xyz

# Chain a follow-up task from a parent
wiggy run --continue-from abc12345 "Add tests for the feature"
```

View history with:

```bash
wiggy history -n 20
```

## Configuration

Wiggy supports two levels of configuration via YAML files:

- **Global:** `~/.wiggy/config.yaml` — user-wide defaults
- **Local:** `.wiggy/config.yaml` — per-project overrides

Local config takes precedence over global. Run the interactive wizard to set up:

```bash
wiggy init --global   # Set up global defaults
wiggy init            # Set up local project config
wiggy init --show     # Show resolved config
```

Configurable options include engine, executor, image, model, parallel count, worktree root, push/PR behavior, and git remote.

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
│   ├── messages.py  # ParsedMessage, MessageType, SessionSummary
│   ├── claude.py    # Claude stream-json parser
│   └── raw.py       # Raw passthrough parser
├── git/             # Git operations
│   ├── worktree.py  # WorktreeManager for isolated execution
│   └── operations.py# Push & PR creation via gh CLI
├── history/         # Task history & persistence
│   ├── models.py    # TaskLog, TaskResult dataclasses
│   ├── repository.py# SQLite-backed storage
│   ├── schema.py    # DB schema & migrations
│   └── cleanup.py   # Old task cleanup
├── tasks/           # Named task system
│   ├── base.py      # TaskSpec dataclass
│   ├── loader.py    # Task discovery from YAML
│   └── default/     # Built-in tasks (analyse, implement, review, ...)
├── mcp/             # Model Context Protocol (WIP)
│   └── compression.py
└── config/          # Configuration & validation
    ├── schema.py    # WiggyConfig dataclass
    ├── loader.py    # Config file loading/saving
    ├── wizard.py    # Interactive config setup
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
