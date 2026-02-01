# Chunk 05: Orchestrator Prompt Templates

## Objective

Create the three orchestrator task definitions (`orchestrator-pre`, `orchestrator-post`, `orchestrator-finalize`) as default tasks, following the existing task system conventions.

## Scope

**Files to create:**

- `src/wiggy/tasks/default/orchestrator-pre/task.yaml`
- `src/wiggy/tasks/default/orchestrator-pre/prompt.md`
- `src/wiggy/tasks/default/orchestrator-post/task.yaml`
- `src/wiggy/tasks/default/orchestrator-post/prompt.md`
- `src/wiggy/tasks/default/orchestrator-finalize/task.yaml`
- `src/wiggy/tasks/default/orchestrator-finalize/prompt.md`

**Files NOT touched:** No code changes. These are pure content files loaded by the existing task system.

**Dependencies from previous chunks:**

- Chunk 02: MCP tool names (referenced in prompts).

## Detailed Requirements

### 1. `orchestrator-pre` — Planning & Decision

**task.yaml:**
```yaml
name: orchestrator-pre
description: Process orchestrator - pre-step planning and decision
```

**prompt.md** should instruct the agent to:

- **Role:** You are a process orchestrator — a supervisory agent that plans and controls the execution of a multi-step coding process.
- **Context:** You will receive the process plan, current state, and upcoming step details via MCP tools.
- **Available tools:** `get_process_state`, `set_process_decision`, `get_git_diff`, `get_commit_log`, plus all shared tools (results, artifacts, knowledge).
- **Protocol:**
  1. Call `get_process_state` to understand where the process stands.
  2. Review results from prior steps using `load_result` / `read_result_summary`.
  3. Check git state via `get_git_diff` and `get_commit_log` if relevant.
  4. Evaluate whether the upcoming step should proceed as-is, needs intermediate work first, or the process should abort.
  5. **You MUST call `set_process_decision`** with one of: `proceed`, `inject`, or `abort`.
- **Decision guidelines:**
  - `proceed`: The process is on track, the next step can run.
  - `inject`: Intermediate work is needed before the next step (e.g., a fix-up implementation after a review found issues). Provide the steps to inject.
  - `abort`: The process cannot continue (e.g., fundamental requirement mismatch, repeated failures).
- **Tone:** Be concise and decisive. You are a supervisor, not a worker.

### 2. `orchestrator-post` — Review & Assessment

**task.yaml:**
```yaml
name: orchestrator-post
description: Process orchestrator - post-step review and assessment
```

**prompt.md** should instruct the agent to:

- **Role:** You are a critical reviewer assessing the output of a just-completed process step.
- **Context:** You will receive the step's result and can inspect the git changes it produced.
- **Available tools:** Same as pre-step.
- **Protocol:**
  1. Call `get_process_state` to see the current state.
  2. Load the just-completed step's result via `load_result` or `read_result_summary`.
  3. Review git changes via `get_git_diff` and `get_commit_log`.
  4. Assess quality, correctness, and completeness.
  5. Record your findings by writing a result (via `write_result`) summarizing your review.
  6. Optionally write knowledge entries for important findings.
- **No flow control:** Post-step does NOT call `set_process_decision`. It only reviews and records. The next pre-step will read your review and make the decision.
- **Evaluation criteria:** Correctness, completeness, adherence to the step's stated goals, code quality, potential issues.

### 3. `orchestrator-finalize` — PR Description & Summary

**task.yaml:**
```yaml
name: orchestrator-finalize
description: Process orchestrator - finalization and PR description generation
```

**prompt.md** should instruct the agent to:

- **Role:** You are finalizing a completed multi-step coding process by generating a PR description and process summary.
- **Context:** All steps have completed. You have access to the full history.
- **Available tools:** Same as pre-step, plus `write_artifact` with template `pr_description`.
- **Protocol:**
  1. Call `get_process_state` to review the full process outcome.
  2. Load results from all steps.
  3. Review the complete git diff and commit log.
  4. Generate a PR description and write it as an artifact using `write_artifact` with template name `pr_description`.
  5. Optionally write a process summary to the knowledge base.
- **PR description format:**
  ```
  ## Summary
  [1-3 sentence overview of what was done]

  ## Changes
  [Bulleted list of key changes with rationale]

  ## Test Plan
  [How to verify the changes]
  ```
- Call `set_process_decision` with `proceed` to signal successful finalization.

### 4. Dynamic Context Injection

The prompt templates are static. Dynamic context (process state, step details, git diffs) is provided via MCP tools that the agent calls during execution. The process runner only needs to set up the MCP environment correctly — no prompt string interpolation needed for dynamic data.

However, include a `{process_context}` placeholder in each prompt where the process runner can inject a brief orientation block (e.g., "You are reviewing step 3 of 5: 'implement'. The process is 'implement-feature'."). This follows the existing pattern where the runner injects process status via `build_process_status_prompt()`.

## Boundary Constraints

- These are content-only files — no Python code changes.
- Do NOT create the `pr_description` artifact template — that is chunk 08.
- Do NOT modify the task loader or process runner.
- Prompts should reference MCP tools by their exact names from chunks 02/07.

## Verification

- Task loader discovers all three tasks: `get_task_by_name("orchestrator-pre")`, etc.
- `ruff check` and `mypy` still pass (no code changes).
- Prompt content is well-structured and actionable for an AI agent.
