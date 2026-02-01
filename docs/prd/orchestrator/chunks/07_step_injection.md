# Chunk 07: Step Injection — `inject_steps` MCP Tool & Loop Guard

## Objective

Implement the `inject_steps` MCP tool, wire step insertion into the process runner, and add the injection loop guard to prevent infinite remediation cycles.

## Scope

**Files to modify:**

- `src/wiggy/mcp/tools.py` — Add `inject_steps` tool handler.
- `src/wiggy/mcp/server.py` — Register the tool (with `orchestrator` scope).
- `src/wiggy/mcp/__init__.py` — Add to `MCP_TOOL_NAMES`.
- `src/wiggy/processes/orchestrator.py` — Replace the injection stub from chunk 06 with actual step insertion logic; add injection counter and loop guard.
- `src/wiggy/processes/base.py` — Add `origin_step_index: int | None = None` to `ProcessStep` for traceability.

**Dependencies from previous chunks:**

- Chunk 02: MCP tool infrastructure.
- Chunk 03: Tool scoping (inject_steps scoped as `orchestrator`).
- Chunk 04: `max_injections` config.
- Chunk 06: Process runner with orchestrator loop (injection stub).

## Detailed Requirements

### 1. `inject_steps` MCP Tool

**Inputs:**
- `steps`: list of objects, each with:
  - `task_name`: str — name of the task to run (must be a valid task).
  - `prompt`: str — prompt/instructions for the injected step.

**Behavior:**
- Validate each `task_name` resolves via `get_task_by_name()`.
- Store the injection request in the DB (associated with the current orchestrator's task_id and process_id).
- Return confirmation with the number of steps to be injected.

**Note:** The tool records the injection request. The actual step insertion into `ProcessRun.steps` is done by the process runner after the orchestrator exits (the orchestrator runs in a container — it cannot directly mutate the runner's in-memory state).

### 2. Step Insertion in Process Runner

When the orchestrator's decision is `"inject"`:

1. Read the injected steps from the `orchestrator_decision` record (or a separate `injected_steps` table populated by the MCP tool).
2. Create `ProcessStep` objects with `origin_step_index` set to the current step index.
3. Insert them into `process_run.steps` at the current position (before the step that triggered the injection).
4. `continue` the loop to re-evaluate with the orchestrator on the first injected step.

### 3. `ProcessStep.origin_step_index`

Add field:

```python
@dataclass
class ProcessStep:
    task: str
    engine: str | None = None
    model: str | None = None
    tools: tuple[str, ...] | None = None
    prompt: str | None = None
    skip_orchestrator: bool = False
    origin_step_index: int | None = None  # NEW: tracks which step triggered injection
```

Injected steps have `origin_step_index` set; original steps have `None`.

### 4. Injection Loop Guard

Track injection count per original step index:

```python
injection_counts: dict[int, int] = {}  # origin_step_index → count
```

Before processing an injection decision:

1. Look up `injection_counts[current_step_index]`.
2. If count >= `orchestrator_config.max_injections`:
   - Log a warning: "Injection limit reached for step {i}. Forcing proceed."
   - Override the decision to `proceed`.
3. Otherwise, increment the count and proceed with injection.

### 5. Injected Step Behavior

- Injected steps run with the same engine/model as regular steps (unless overridden in the injection request).
- Injected steps have `skip_orchestrator = False` by default (the orchestrator reviews them too).
- Injected steps appear in the process summary with their origin noted.

## Boundary Constraints

- Do NOT modify PR description generation — that is chunk 08.
- Do NOT modify config schema — that was chunk 04.
- Do NOT modify prompt templates — that was chunk 05.

## Verification

- All existing tests pass.
- `mypy src/` and `ruff check src/` pass.
- New tests:
  - `inject_steps` MCP tool validates task names and records injection.
  - Process runner inserts steps at the correct position.
  - Loop guard triggers after `max_injections` reached.
  - `origin_step_index` is set correctly on injected steps.
  - Injected steps execute and are reviewed by the orchestrator.
  - End-to-end: review step finds issue → orchestrator injects fix → fix runs → process continues.
