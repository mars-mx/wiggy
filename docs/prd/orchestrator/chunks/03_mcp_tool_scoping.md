# Chunk 03: MCP Tool Scoping — Shared vs Orchestrator-Exclusive

## Objective

Enforce that orchestrator-only MCP tools (`get_process_state`, `set_process_decision`, `get_git_diff`, `get_commit_log`, and later `inject_steps`) are only visible to and callable by orchestrator tasks. Regular task agents must not see or invoke these tools.

## Scope

**Files to modify:**

- `src/wiggy/mcp/server.py` — Add scope metadata to tool registrations; filter `tools/list` responses based on `is_orchestrator`; add call-time rejection guard.
- `src/wiggy/mcp/tools.py` — Annotate each tool with its scope (`"shared"` or `"orchestrator"`).

**Dependencies from previous chunks:**

- Chunk 01: `TaskLog.is_orchestrator` field and DB column.
- Chunk 02: The five new MCP tools are registered.

## Detailed Requirements

### 1. Tool Scope Annotation

Each MCP tool gets a scope: `"shared"` (default, available to all) or `"orchestrator"` (only available to orchestrator tasks).

**Shared tools** (all existing 12 tools):
- `write_result`, `load_result`, `read_result_summary`
- `write_artifact`, `load_artifact`, `list_artifacts`, `list_artifact_templates`, `load_artifact_template`
- `write_knowledge`, `get_knowledge`, `view_knowledge_history`, `search_knowledge`

**Orchestrator-exclusive tools**:
- `get_process_state`
- `set_process_decision`
- `get_git_diff`
- `get_commit_log`
- `inject_steps` (added in chunk 07, but the scoping infrastructure must support it now)

### 2. Layer 1: Tool List Filtering (Primary Gate)

When a client calls `tools/list` during MCP capability negotiation:

1. Extract `X-Wiggy-Task-ID` from the request headers.
2. Look up the `TaskLog` in the DB.
3. Check `is_orchestrator` flag.
4. If `is_orchestrator=True`: return all tools.
5. If `is_orchestrator=False`: return only `shared`-scoped tools.

This means orchestrator-only tools never enter a regular agent's context — the agent doesn't know they exist.

### 3. Layer 2: Call-Time Rejection (Defense-in-Depth)

On every tool invocation:

1. Extract `X-Wiggy-Task-ID` from headers.
2. Look up `TaskLog.is_orchestrator`.
3. If the tool's scope is `"orchestrator"` and `is_orchestrator=False`, return an error: `"Tool '{name}' is not available for this task type."`

This guards against cached tool lists or prompt injection attempts.

### 4. Implementation Strategy

The approach depends on what FastMCP supports. Options:

**Option A** (preferred): If FastMCP supports middleware or request hooks, add filtering there.

**Option B**: Wrap tool registration with scope metadata and override the `tools/list` handler to filter based on headers.

**Option C**: If neither is clean, create a thin wrapper that intercepts requests before they reach FastMCP.

Choose whichever integrates cleanest with the existing `WiggyMCPServer` class.

## Boundary Constraints

- Do NOT modify the process runner or CLI.
- Do NOT add new tools — only add scoping to existing registrations.
- Do NOT change config schema.
- Ensure backward compatibility: if `X-Wiggy-Task-ID` is missing or the task_log has no `is_orchestrator` field, default to `shared`-only access.

## Verification

- All existing tests pass (existing tools remain accessible to regular tasks).
- `mypy src/` and `ruff check src/` pass.
- New tests:
  - Regular task calling `tools/list` does NOT see orchestrator tools.
  - Orchestrator task calling `tools/list` sees ALL tools.
  - Regular task calling an orchestrator tool directly gets an error response.
  - Orchestrator task calling an orchestrator tool succeeds.
