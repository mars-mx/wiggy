# Task System Implementation Plan

## Overview

Add a `wiggy task` CLI command for running and creating tasks, with tasks managed as files in `~/.wiggy/tasks/` (global) and `./.wiggy/tasks/` (local).

## Commands

```bash
wiggy task list [--verbose]           # List available tasks
wiggy task <name>                     # Run a task (shortcut)
wiggy task run <name> [options]       # Run a task with options
wiggy task create [--local]           # Create new task via AI (default: global)
```

---

## Design Decisions

### 1. Task Storage

**Default behavior (`wiggy init`):**
- Copy all default tasks from package to `~/.wiggy/tasks/` (global)
- Users can customize these copies
- Package defaults serve as source, not runtime fallback

**With `--local` flag (`wiggy init --local`):**
- Copy default tasks to `./.wiggy/tasks/` (project-specific)
- Allows per-project task customization

**Resolution order:**
1. `./.wiggy/tasks/<name>/` (local project - highest priority)
2. `~/.wiggy/tasks/<name>/` (global user)

No package fallback at runtime - tasks must exist in one of these locations.

### 2. Container Mounting

For task execution, mount both:
- Current directory → `/workspace` (read-write)
- `~/.wiggy/tasks/` → `/home/wiggy/.wiggy/tasks/` (read-only)

This allows `--append-system-prompt` to reference task prompts directly.

### 3. System Prompt Handling

All task prompts are appended via `--append-system-prompt`:
```
claude --append-system-prompt /home/wiggy/.wiggy/tasks/<task>/prompt.md \
       --allowedTools "Read,Write,Edit,Bash,Glob,Grep" \
       --dangerously-skip-permissions --print --verbose \
       --output-format stream-json \
       "<user-prompt>"
```

### 4. Tool Restriction

The `tools` field in `task.yaml` maps to the `--allowedTools` CLI flag:

| task.yaml tools | CLI flag |
|-----------------|----------|
| `["*"]` | (omit flag - all tools allowed) |
| `["Read", "Write"]` | `--allowedTools "Read,Write"` |
| `[]` | `--allowedTools ""` (no tools) |

**Available tools for Claude Code (non-interactive mode):**
- **File operations:** `Read`, `Write`, `Edit`, `Glob`, `Grep`, `NotebookEdit`
- **Shell:** `Bash`
- **Web:** `WebFetch`, `WebSearch`
- **Sub-agents:** `Task`

Note: Interactive tools like `AskUserQuestion` are not available in non-interactive/print mode.

---

## Files to Modify

### 1. `src/wiggy/cli.py`

Add `task` command group:

```python
@main.group(invoke_without_command=True)
@click.argument("task_name", required=False)
@click.pass_context
def task(ctx: click.Context, task_name: str | None) -> None:
    """Run and manage tasks."""
    if ctx.invoked_subcommand is None:
        if task_name:
            ctx.invoke(task_run, task_name=task_name)
        else:
            click.echo(ctx.get_help())
```

**Subcommands:**
- `task list` - List tasks with source labels (global/local)
- `task run <name>` - Run task with options: `--engine`, `--model`, `--prompt`
  - Loads TaskSpec, extracts `tools` field
  - Passes tools to executor via `allowed_tools` parameter
  - Appends task's prompt.md via `--append-system-prompt`
- `task create [--local]` - Interactive task creation (default: global)

**Helper functions:**
- `_format_tasks_context(tasks)` - Format tasks as name + description + tools
- `_get_source_label(source)` - Returns "(global)" or "(local)"

### 2. `src/wiggy/config/init.py`

Add function to copy default tasks:

Add imports at top of file:
```python
import shutil
from importlib.resources import files
```

Add function:
```python
def copy_default_tasks(local: bool = False) -> None:
    """Copy default tasks from package to task directory.

    Args:
        local: If True, copy to ./.wiggy/tasks/ (project-local).
               If False, copy to ~/.wiggy/tasks/ (global, default).
    """
    package_tasks = files("wiggy.tasks.default")

    if local:
        target = Path.cwd() / ".wiggy" / "tasks"
    else:
        target = Path.home() / ".wiggy" / "tasks"

    target.mkdir(parents=True, exist_ok=True)

    for task_dir in package_tasks.iterdir():
        if task_dir.is_dir():
            dest = target / task_dir.name
            if not dest.exists():
                shutil.copytree(task_dir, dest)
```

- `wiggy init` (default) → copies to `~/.wiggy/tasks/`
- `wiggy init --local` → copies to `./.wiggy/tasks/`

### 3. `src/wiggy/executors/docker.py`

**Modify `_build_command()`:**
```python
def _build_command(self, engine: Engine, prompt: str | None) -> list[str]:
    command = [engine.cli_command]
    if self._model_override:
        command.extend(["--model", self._model_override])
    # Add allowed tools if specified (not "*")
    if self._allowed_tools and self._allowed_tools != ["*"]:
        command.extend(["--allowedTools", ",".join(self._allowed_tools)])
    command.extend(self._extra_args)  # Extra args (e.g., --append-system-prompt)
    command.extend(engine.default_args)
    if prompt:
        command.append(prompt)
    return command
```

**Add `allowed_tools` parameter to `__init__()`:**
```python
def __init__(
    self,
    ...
    extra_args: tuple[str, ...] = (),
    allowed_tools: list[str] | None = None,
) -> None:
    self._extra_args = extra_args
    self._allowed_tools = allowed_tools
```

**Modify `_get_volume_mounts()`:**
```python
def _get_volume_mounts(self, engine: Engine) -> dict[str, dict[str, str]]:
    volumes = {}

    # Existing worktree mount...

    # Mount global tasks directory (read-only)
    global_tasks = Path.home() / ".wiggy" / "tasks"
    if global_tasks.exists():
        volumes[str(global_tasks)] = {
            "bind": "/home/wiggy/.wiggy/tasks",
            "mode": "ro",
        }

    # Existing credentials mount...
    return volumes
```

### 4. `src/wiggy/executors/__init__.py`

Update `get_executor()` and `get_executors()` to accept new parameters:
- `extra_args: tuple[str, ...]` - Additional CLI args (e.g., `--append-system-prompt`)
- `allowed_tools: list[str] | None` - Tools from task.yaml

### 5. `src/wiggy/tasks/loader.py`

Update to only look in filesystem locations (remove package fallback):

```python
def get_task_search_paths() -> list[Path]:
    """Return task search paths in priority order."""
    paths = []

    # Local project tasks (highest priority)
    local = Path.cwd() / ".wiggy" / "tasks"
    if local.exists():
        paths.append(local)

    # Global user tasks
    global_tasks = Path.home() / ".wiggy" / "tasks"
    if global_tasks.exists():
        paths.append(global_tasks)

    return paths
```

---

## Files to Create

### 1. `src/wiggy/tasks/default/create-task/task.yaml`

```yaml
name: create-task
description: |
  Meta-task for creating new wiggy tasks. Generates task.yaml
  and prompt.md files based on user goals.
tools:
  - Write
  - Read
  - Bash
```

### 2. `src/wiggy/tasks/default/create-task/prompt.md`

```markdown
# Create Task Specification

You are creating a new wiggy task. A task is a reusable prompt template
that guides AI assistants through specific types of work.

## Task Structure

Each task is a directory containing:

1. **task.yaml** - Metadata:
   ```yaml
   name: task-name          # lowercase, hyphenated
   description: |
     Clear description of what this task accomplishes.
   tools:
     - Write                 # List specific tools, or use "*" for all
     - Read
     - Bash
   model: null              # Optional: specific model preference
   ```

2. **prompt.md** - The prompt that guides the AI:
   - Clear objectives
   - Step-by-step guidelines
   - Constraints and best practices
   - Keep it focused and actionable

## Available Tools

When specifying tools in task.yaml, use these exact names:

| Tool | Description |
|------|-------------|
| `Read` | Read file contents |
| `Write` | Create or overwrite files |
| `Edit` | Make targeted edits to files |
| `Glob` | Find files by pattern (e.g., `**/*.py`) |
| `Grep` | Search for patterns in file contents |
| `Bash` | Execute shell commands |
| `NotebookEdit` | Modify Jupyter notebook cells |
| `WebFetch` | Fetch content from URLs |
| `WebSearch` | Search the web |
| `Task` | Spawn sub-agents for complex work |
| `*` | Allow all tools (use sparingly) |

**Best practice:** Only include tools the task actually needs. Restricting
tools improves safety and focuses the AI on the task at hand.

## Instructions

Based on the user's goal, create a new task:

1. Choose an appropriate task name (lowercase, hyphenated)
2. Determine which tools are needed (prefer minimal set)
3. Write a clear, effective prompt.md

Create the files at the target directory specified in the user's prompt.

Use the Write tool to create:
- `<target-dir>/<task-name>/task.yaml`
- `<target-dir>/<task-name>/prompt.md`
```

### 3. `tests/test_task_cli.py`

```python
"""Tests for the task CLI commands."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from wiggy.cli import main


def test_task_list_shows_tasks(tmp_path: Path) -> None:
    """Test that 'wiggy task list' shows available tasks."""
    # Create a mock task
    task_dir = tmp_path / ".wiggy" / "tasks" / "test-task"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text("name: test-task\ndescription: A test\ntools: ['*']")
    (task_dir / "prompt.md").write_text("# Test prompt")

    with patch("wiggy.tasks.loader.get_task_search_paths", return_value=[tmp_path / ".wiggy" / "tasks"]):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "list"])
        assert result.exit_code == 0
        assert "test-task" in result.output


def test_task_run_unknown_shows_error() -> None:
    """Test that running unknown task shows error."""
    runner = CliRunner()
    result = runner.invoke(main, ["task", "run", "nonexistent-task"])
    assert result.exit_code == 1
    assert "Unknown task" in result.output or "not found" in result.output.lower()
```

---

## `task create` Execution Flow

1. User runs `wiggy task create [--local]`
2. CLI prompts: "What do you want this task to achieve?"
3. CLI builds main prompt:
   ```
   ## Goal
   <user's description>

   ## Existing Tasks (for reference)

   ### analyse
   Deep code analysis and architecture review.
   Tools: *

   ### implement
   Implement features based on specifications.
   Tools: Write, Read, Bash, Grep, Glob

   ...
   ```
4. CLI resolves `create-task` prompt.md path
5. Determine target directory:
   - Default: `~/.wiggy/tasks/` (global)
   - With `--local`: `./.wiggy/tasks/` (project-local)
6. Run executor with:
   - `extra_args=("--append-system-prompt", "/home/wiggy/.wiggy/tasks/create-task/prompt.md")`
   - No worktree (mounts cwd directly)
   - Main prompt = goal + existing tasks context + target directory
7. AI creates files in target directory
8. Confirm success

---

## Implementation Sequence

1. **Update `config/init.py`** - Add `copy_default_tasks(local: bool)`
2. **Update `wiggy init`** - Call task copy (default: global, `--local`: project-local)
3. **Update `executors/docker.py`** - Add `extra_args` and global tasks mount
4. **Update `executors/__init__.py`** - Pass through `extra_args`
5. **Update `tasks/loader.py`** - Remove package fallback, filesystem only
6. **Create `create-task`** - New default task
7. **Add `task` command group** - With `list`, `run`, `create` subcommands
8. **Add tests**

---

## Verification

```bash
# Initialize with default tasks (global by default)
wiggy init

# Verify tasks copied to global location
ls ~/.wiggy/tasks/

# Initialize with local tasks (project-specific)
wiggy init --local
ls ./.wiggy/tasks/

# List tasks
wiggy task list

# Run a task
wiggy task analyse

# Create a new task (global by default)
wiggy task create

# Create a local task
wiggy task create --local

# Run tests
.venv/bin/pytest tests/test_task_cli.py

# Lint and type check
.venv/bin/ruff check src/wiggy/
.venv/bin/mypy src/wiggy/
```
