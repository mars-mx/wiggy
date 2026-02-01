# Chunk 06: Process Runner Integration — Orchestrator Loop

## Objective

Modify `run_process()` in the process runner to invoke the orchestrator agent before and after each step, and run a finalization phase after all steps complete. This is the core integration that wires everything together.

## Scope

**Files to modify:**

- `src/wiggy/processes/orchestrator.py` — Major changes to `run_process()` to add orchestrator invocations.

**Dependencies from previous chunks:**

- Chunk 01: `OrchestratorDecision` model, `ProcessRun.orchestrator_decisions`, `TaskLog.is_orchestrator`, repository methods.
- Chunk 02: MCP tools available for the orchestrator to call.
- Chunk 03: Tool scoping ensures orchestrator gets the right tools.
- Chunk 04: `OrchestratorConfig`, `skip_orchestrator`, `resolve_orchestrator_config()`.
- Chunk 05: Orchestrator task definitions (`orchestrator-pre`, `orchestrator-post`, `orchestrator-finalize`).

## Detailed Requirements

### 1. Orchestrator Invocation Helper

Create a helper function:

```python
async def run_orchestrator_phase(
    phase: str,                    # "pre_step", "post_step", "finalize"
    step_index: int,
    process_run: ProcessRun,
    orchestrator_config: OrchestratorConfig,
    worktree_info: WorktreeInfo,
    git_author_name: str | None,
    git_author_email: str | None,
) -> OrchestratorDecision | None:
```

This function:

1. Resolves the task definition: `get_task_by_name(f"orchestrator-{phase_suffix}")` where phase_suffix is `pre`, `post`, or `finalize`.
2. Creates a `TaskLog` with `is_orchestrator=True` and `task_name=f"orchestrator-{phase_suffix}"`.
3. Builds the process context prompt (orientation block injected into the task prompt).
4. Runs the task via `DockerExecutor` with the orchestrator's engine/model from config.
5. After execution, reads the `orchestrator_decision` record from the DB (written by the agent via `set_process_decision` MCP tool).
6. Returns the decision (or `None` if the phase doesn't produce one, i.e., post-step).

### 2. Modified `run_process()` Loop

```python
orchestrator_config = resolve_orchestrator_config(global_config, process_spec)

for i, step in enumerate(process_run.steps):
    process_run.current_index = i

    if orchestrator_config.enabled and not step.skip_orchestrator:
        # PRE-STEP
        decision = await run_orchestrator_phase(
            phase="pre_step", step_index=i, ...
        )
        process_run.orchestrator_decisions.append(decision)

        if decision.decision == "abort":
            # Record abort reason, break
            break

        if decision.decision == "inject":
            # Insert new steps (handled in chunk 07)
            # For now: log warning that injection is not yet supported
            pass

    # RUN THE STEP (existing logic)
    result = await run_step(step, ...)
    process_run.results.append(result)

    if orchestrator_config.enabled and not step.skip_orchestrator:
        # POST-STEP
        await run_orchestrator_phase(
            phase="post_step", step_index=i, ...
        )

# FINALIZATION
if orchestrator_config.enabled:
    await run_orchestrator_phase(
        phase="finalize", step_index=len(process_run.steps), ...
    )
```

### 3. Process Context Prompt

Build an orientation block injected into each orchestrator invocation:

```
Process: {process_name} ({process_id})
Phase: {phase} for step {step_index + 1} of {total_steps}
Step: {step.task} {("— " + step.prompt) if step.prompt else ""}
Completed steps: {completed_count}/{total_steps}
```

This extends the existing `build_process_status_prompt()` or is built alongside it.

### 4. Executor Setup for Orchestrator

The orchestrator runs in a Docker container like any other task, but with:

- `is_orchestrator=True` in the `TaskLog` (so MCP scoping works).
- Engine and model from `OrchestratorConfig`.
- Same worktree as the process.
- Same MCP server connection.

### 5. Error Handling

- If the orchestrator task itself fails (non-zero exit), log a warning and **proceed** with the process (graceful degradation). The orchestrator is advisory — a crash should not block the process.
- If `set_process_decision` was not called by the orchestrator (no decision record in DB), default to `proceed` with a logged warning.

## Boundary Constraints

- Step injection (`decision == "inject"`) should be stubbed with a warning log — full implementation is chunk 07.
- PR description retrieval is not wired yet — that is chunk 08.
- Do NOT modify MCP tools or config schema.
- Keep the existing fail-fast behavior for actual task steps unchanged.

## Verification

- All existing tests pass.
- `mypy src/` and `ruff check src/` pass.
- New integration tests:
  - Process runs with orchestrator enabled: pre/post/finalize phases execute.
  - Process runs with orchestrator disabled: no orchestrator invocations.
  - `skip_orchestrator` on a step: that step has no pre/post.
  - Orchestrator failure (crash): process continues gracefully.
  - Orchestrator abort decision: process stops with reason recorded.
