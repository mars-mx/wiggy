# Chunk 02: MCP Tools — Process State, Decision Recording, Git Inspection

## Objective

Implement five new MCP tools: `get_process_state`, `set_process_decision`, `get_git_diff`, `get_commit_log`, and expose them on the MCP server. These tools are registered but not yet scoped (scoping is chunk 03).

## Scope

**Files to modify:**

- `src/wiggy/mcp/tools.py` — Add tool handler functions for the five new tools.
- `src/wiggy/mcp/server.py` — Register the new tools with the FastMCP server.
- `src/wiggy/mcp/__init__.py` — Add new tool names to `MCP_TOOL_NAMES`.

**Dependencies from previous chunks:**

- Chunk 01: `OrchestratorDecision` model, `orchestrator_decision` DB table, repository methods.

## Detailed Requirements

### 1. `get_process_state`

Returns the full current process state for the calling task's process.

**Inputs:** None (process_id derived from task_id → task_log.process_id).

**Returns:** JSON object with:
- `process_id`: str
- `process_name`: str
- `completed_steps`: list of `{index, task_name, task_id, success, exit_code, duration_ms}`
- `pending_steps`: list of `{index, task_name}`
- `current_index`: int
- `orchestrator_decisions`: list of prior decisions

**Implementation:** Query `task_log` by `process_id` joined with `task_result` for completed steps. Query `orchestrator_decision` table for decisions. Derive pending steps from the process spec stored in context.

Note: The process runner must make the current `ProcessRun` state accessible to the MCP server. The simplest approach: store a serialized process state snapshot in the DB (or a shared in-memory dict keyed by process_id) that the runner updates after each step. Choose the approach that fits the existing architecture — the MCP server is stateless HTTP, so DB is preferred.

### 2. `set_process_decision`

Records the orchestrator's decision for the current phase.

**Inputs:**
- `decision`: str — one of `"proceed"`, `"inject"`, `"abort"`
- `reasoning`: str — explanation of the decision
- `injected_steps`: optional list of `{task_name, prompt}` — only when decision is `"inject"`

**Behavior:**
- Validates `decision` is one of the allowed values.
- Writes an `orchestrator_decision` record to the DB.
- If `decision == "inject"` and `injected_steps` is empty, return an error.
- If `decision != "inject"` and `injected_steps` is provided, return an error.

**Returns:** Confirmation with the decision ID.

### 3. `get_git_diff`

Returns the git diff for the process worktree.

**Inputs:**
- `since_commit`: optional str — if provided, diff since that commit. Otherwise diff since the first commit of the process.

**Implementation:**
- Look up the task's `worktree` path from `task_log`.
- Run `git diff <since_commit>..HEAD` in that worktree directory.
- If `since_commit` is not provided, look up the earliest `task_refs.commit_hash` for the process and diff from there.
- Truncate output if it exceeds a reasonable limit (e.g., 50KB) with a note.

### 4. `get_commit_log`

Returns commit messages since the process started.

**Inputs:**
- `since_commit`: optional str — same semantics as `get_git_diff`.

**Implementation:**
- Look up worktree path.
- Run `git log --oneline <since_commit>..HEAD` in the worktree.
- Return as a list of `{hash, message}` objects.

## Boundary Constraints

- All five tools are registered as regular tools — no scoping yet (chunk 03 adds scoping).
- Do NOT modify the process runner — that is chunk 06.
- Do NOT add `inject_steps` tool — that is chunk 07.
- Git operations should use `subprocess.run` with appropriate error handling, matching patterns already used in `src/wiggy/git/`.

## Verification

- All existing tests pass.
- `mypy src/` and `ruff check src/` pass.
- New unit tests for each tool handler with mocked DB and git operations.
- Manual verification: start MCP server, call each tool, verify response shape.
