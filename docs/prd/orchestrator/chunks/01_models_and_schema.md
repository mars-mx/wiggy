# Chunk 01: OrchestratorDecision Model, ProcessRun Mutations & DB Schema

## Objective

Add the `OrchestratorDecision` dataclass, make `ProcessRun` track orchestrator decisions, add the `is_orchestrator` flag to `TaskLog`, and create the `orchestrator_decision` DB table.

## Scope

**Files to modify:**

- `src/wiggy/processes/base.py` — Add `OrchestratorDecision` dataclass; add `orchestrator_decisions` field to `ProcessRun`.
- `src/wiggy/history/models.py` — Add `is_orchestrator: bool = False` field to `TaskLog`.
- `src/wiggy/history/schema.py` — Add `orchestrator_decision` table; add `is_orchestrator` column to `task_log`; bump schema version.
- `src/wiggy/history/repository.py` — Add CRUD methods for `OrchestratorDecision`; update `TaskLog` insert/select to include `is_orchestrator`.

**Files NOT touched:** MCP server, process runner, config, CLI, executors, prompt templates.

## Detailed Requirements

### 1. `OrchestratorDecision` dataclass

Location: `src/wiggy/processes/base.py`

```python
@dataclass(frozen=True)
class OrchestratorDecision:
    phase: str                    # "pre_step", "post_step", "finalize"
    step_index: int
    decision: str                 # "proceed", "inject", "abort"
    reasoning: str
    injected_steps: tuple[ProcessStep, ...] = ()
    task_id: str = ""             # orchestrator's own task_id
    created_at: str = ""
```

### 2. `ProcessRun` changes

Add field:

```python
orchestrator_decisions: list[OrchestratorDecision]  # audit trail
```

Initialize to `[]` in `__post_init__`.

### 3. `TaskLog` changes

Add field `is_orchestrator: bool = False` to the existing `TaskLog` frozen dataclass. This is used later by MCP tool scoping to determine which tools to expose.

### 4. DB schema changes

Bump schema version from 4 to 5.

Add `is_orchestrator` boolean column (default 0) to `task_log` table.

Add new table:

```sql
CREATE TABLE IF NOT EXISTS orchestrator_decision (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    decision TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    injected_steps TEXT,          -- JSON serialized
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task_log(task_id)
);
CREATE INDEX IF NOT EXISTS idx_orchestrator_decision_process_id ON orchestrator_decision(process_id);
```

Add migration path from v4 → v5 (ALTER TABLE + CREATE TABLE).

### 5. Repository methods

Add to `TaskHistoryRepository`:

- `save_orchestrator_decision(process_id: str, decision: OrchestratorDecision) -> None`
- `get_orchestrator_decisions(process_id: str) -> list[OrchestratorDecision]`

Update existing `create_task_log()` and `get_task_log()` to handle `is_orchestrator` field.

## Boundary Constraints

- Do NOT wire anything into the process runner yet — that is a later chunk.
- Do NOT add MCP tools — that is a later chunk.
- Do NOT modify config schema — that is a later chunk.
- Focus purely on data models, schema, and persistence.

## Verification

- All existing tests pass (`pytest tests/`).
- `mypy src/` passes with no new errors.
- `ruff check src/` passes.
- New unit tests for `OrchestratorDecision` serialization round-trip and repository methods.
