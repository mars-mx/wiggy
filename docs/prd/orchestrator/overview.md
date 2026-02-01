# PRD: Process Orchestrator

## Status: Draft

## Problem Statement

Currently, process execution in Wiggy is a linear, fail-fast pipeline. Each step runs to completion and the next step begins with no critical review of the output. There is no mechanism to:

1. **Review agent output** between steps and decide if the result is acceptable.
2. **Inject intermediate tasks** (e.g., dispatch a fix-up implementation task when a review step finds issues).
3. **Generate meaningful PR descriptions** — the current PR body is a hardcoded string (`"Automated PR from wiggy session {hash_id}"`).

The orchestrator fills the role of "human-in-the-loop" — an AI agent with a fresh context that supervises the work of other agents, makes judgement calls, and drives the process to completion.

---

## Goals

- Introduce an orchestrator agent that runs **before and after every task** in a process.
- The orchestrator always starts with a **fresh context** (no accumulated drift from long sessions).
- The orchestrator can **inject new steps** into the running process (e.g., a remediation `implement` task after a failed review).
- The orchestrator generates the **PR description** as a final artifact.
- The orchestrator runs via the **Docker executor**, same as other tasks.

## Non-Goals

- Replacing the existing sequential process runner — the orchestrator augments it.
- Giving the orchestrator direct write access to the codebase — it operates through dispatching tasks and producing artifacts.
- Parallel orchestration of multiple processes.

---

## Architecture Overview

### Current Flow

```
Step 1 → Step 2 → Step 3 → push → PR (hardcoded body)
         (fail-fast on error)
```

### Proposed Flow

```
Orchestrator (pre-step-1)
  → Step 1
    → Orchestrator (post-step-1)
      → [optional injected steps]
        → Orchestrator (pre-step-2)
          → Step 2
            → Orchestrator (post-step-2)
              → Orchestrator (pre-step-3)
                → Step 3
                  → Orchestrator (post-step-3 / finalize)
                    → push → PR (orchestrator-generated body)
```

Pre-step and post-step are **separate invocations**, each in its own Docker container. This keeps each orchestrator call narrowly scoped with a clear, single responsibility — review *or* preparation — rather than overloading a single prompt with both concerns. Steps with `skip_orchestrator: true` bypass both the pre-step and post-step orchestrator invocations.

The orchestrator is a **meta-agent**: it reads results from completed steps via MCP, decides what happens next, and can modify the remaining step queue.

---

## Detailed Design

### 1. Orchestrator Agent

The orchestrator is a special task that runs inside the Docker executor like any other agent, but with elevated MCP capabilities.

**Context provided to the orchestrator on each invocation:**

| Input | Source |
|---|---|
| Process spec (full step list) | `ProcessSpec` |
| Current step index and phase (pre/post) | Injected into prompt |
| Results from all completed steps | MCP `read_result_summary` / `load_result` |
| Artifacts produced so far | MCP `list_artifacts` / `load_artifact` |
| Knowledge base entries | MCP `search_knowledge` |
| Git diff / commit messages since process start | Injected into prompt or via MCP tool |

**Fresh context guarantee:** Each orchestrator invocation is a new Docker container with a new task ID. No state carries over from previous orchestrator runs except what is stored in MCP (results, artifacts, knowledge).

### 2. Orchestrator Responsibilities by Phase

#### Pre-Step Phase

A dedicated invocation that runs before each process step. Responsibilities:

- Review the process plan and upcoming step.
- Decide whether to **proceed**, **inject intermediate steps**, or **abort** the process.
- Provide a concise, focused prompt refinement for the upcoming step if needed.

Skipped for steps with `skip_orchestrator: true`.

#### Post-Step Phase

A separate invocation that runs after each process step completes. Responsibilities:

- Review the just-completed step's output and results.
- Assess quality and correctness of the work produced.
- Record findings that inform the next pre-step decision.

Pre-step and post-step are **always separate container invocations**. This keeps each orchestrator call narrowly scoped: post-step focuses purely on review, pre-step focuses purely on planning. The trade-off is additional container launches, but the clarity of purpose outweighs the overhead.

Skipped for steps with `skip_orchestrator: true`.

#### Finalization Phase

After the last step's post-step review completes:

- Review overall process outcome.
- Generate PR title and description as an **artifact** (e.g., template `pr_description`).
- Optionally write a process summary to the knowledge base.

### 3. MCP Extensions

New MCP tools required for the orchestrator:

| Tool | Description |
|---|---|
| `inject_steps` | Insert one or more new steps into the process queue at a given position. Accepts a list of `{task_name, prompt, position}` objects. |
| `set_process_decision` | Record the orchestrator's decision: `proceed`, `inject`, or `abort`. Required — the orchestrator must call this before exiting. |
| `get_process_state` | Return the full current process state: completed steps with results, pending steps, current index. |
| `get_git_diff` | Return the git diff for the worktree (since process start or since a given commit). |
| `get_commit_log` | Return commit messages since the process started. |

#### Tool Access Matrix

The new orchestrator tools are **exclusive to the orchestrator**. Regular task agents must not have access to process-control or flow-control tools. This enforces a clean separation between workers (task agents) and the supervisor (orchestrator).

| Tool | Task Agents | Orchestrator | Rationale |
|---|---|---|---|
| **Results** | | | |
| `write_result` | yes | yes | Both produce results |
| `load_result` | yes | yes | Both can read prior results |
| `read_result_summary` | yes | yes | Both can read summaries |
| **Artifacts** | | | |
| `write_artifact` | yes | yes | Both produce artifacts |
| `load_artifact` | yes | yes | Both can read artifacts |
| `list_artifacts` | yes | yes | Both can list artifacts |
| `list_artifact_templates` | yes | yes | Both can list templates |
| `load_artifact_template` | yes | yes | Both can load templates |
| **Knowledge** | | | |
| `write_knowledge` | yes | yes | Both contribute knowledge |
| `get_knowledge` | yes | yes | Both can read knowledge |
| `view_knowledge_history` | yes | yes | Both can view history |
| `search_knowledge` | yes | yes | Both can search |
| **Process Control** | | | |
| `inject_steps` | **no** | yes | Only the supervisor dispatches work |
| `set_process_decision` | **no** | yes | Only the supervisor controls flow |
| `get_process_state` | **no** | yes | Task agents get process context via prompt injection (`build_process_status_prompt`); raw state is an orchestrator concern |
| **Git Inspection** | | | |
| `get_git_diff` | **no** | yes | Task agents have git in the worktree already; orchestrator needs MCP access since it reads state rather than running arbitrary commands |
| `get_commit_log` | **no** | yes | Same rationale as `get_git_diff` |

#### Enforcement: Scoped Tool Filtering

Tool access is enforced at two layers — client-side filtering (primary) and server-side guard (defense-in-depth).

**Layer 1: MCP Server Tool Scoping (primary gate)**

Each MCP tool is registered with a scope: `shared` or `orchestrator`.

```python
@mcp.tool(scope="orchestrator")
def inject_steps(...): ...

@mcp.tool(scope="shared")
def write_result(...): ...
```

When an engine calls `tools/list` during MCP capability negotiation, the `X-Wiggy-Task-ID` header is included (already the case for all MCP requests). The server:

1. Extracts the task ID from the `X-Wiggy-Task-ID` header.
2. Looks up the `TaskLog` record in the DB.
3. Checks the `is_orchestrator` flag.
4. Returns **all tools** if `is_orchestrator=True`, or only `shared`-scoped tools if `False`.

This means orchestrator-only tools never appear in a regular agent's tool list — the engine never knows they exist and they never enter the agent's context.

**Prerequisite:** `TaskLog` must be written to the DB (with `is_orchestrator` set) before `executor.setup()`. This is already the case in the current flow — `TaskLog` is created before the container starts, and the task ID is baked into the MCP config headers at container creation time.

**Layer 2: Server-Side Call Rejection (defense-in-depth)**

Even if a task agent somehow calls an orchestrator-only tool (e.g., tool list was cached, or a prompt injection attempts it), the MCP server rejects the call:

1. On every tool invocation, extract `X-Wiggy-Task-ID` from headers.
2. Look up `TaskLog.is_orchestrator`.
3. If the tool's scope is `orchestrator` and `is_orchestrator=False`, return an error.

**`TaskLog` Schema Change:**

```python
@dataclass(frozen=True)
class TaskLog:
    ...
    is_orchestrator: bool = False   # new field
    task_name: str | None = None    # set to "orchestrator" for orchestrator tasks
```

The process runner sets `is_orchestrator=True` and `task_name="orchestrator"` when creating the `TaskLog` for orchestrator invocations.

### 4. Process Run State Changes

`ProcessRun` needs to become mutable with respect to its step list:

```python
@dataclass
class ProcessRun:
    process_id: str
    spec: ProcessSpec
    steps: list[ProcessStep]      # mutable — orchestrator can inject
    results: list[StepResult]
    current_index: int
    worktree_info: WorktreeInfo
    orchestrator_decisions: list[OrchestratorDecision]  # audit trail
```

New model:

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

### 5. Orchestrator Prompt Templates

Since pre-step and post-step have fundamentally different responsibilities, the orchestrator uses **three separate task definitions** (prompt templates), one per phase:

#### `orchestrator-pre` — Planning & Decision

Bundled as a default task at `src/wiggy/tasks/default/orchestrator-pre/` and loaded via the standard task system (`get_task_by_name("orchestrator-pre")`). Users can override per-project at `.wiggy/tasks/orchestrator-pre/`. Prompt focuses on:

- Role description: process planner and decision-maker.
- Available MCP tools and their usage.
- Decision protocol: must always call `set_process_decision` (`proceed`, `inject`, or `abort`).
- Guidelines for when to inject steps vs. proceed.
- Upcoming step context: what the next step is, what it expects.

Dynamically composed per invocation with:

- The upcoming step definition and its prompt.
- Process state snapshot (completed steps, pending steps, current index).

#### `orchestrator-post` — Review & Assessment

Bundled as a default task at `src/wiggy/tasks/default/orchestrator-post/` and loaded via the standard task system (`get_task_by_name("orchestrator-post")`). Users can override per-project at `.wiggy/tasks/orchestrator-post/`. Prompt focuses on:

- Role description: critical reviewer and quality assessor.
- Evaluation criteria: correctness, completeness, adherence to the step's goals.
- How to record findings via MCP (results, knowledge) so the next pre-step can act on them.
- No decision protocol — post-step does not control flow, it only reviews.

Dynamically composed per invocation with:

- The just-completed step's definition, prompt, and result.
- Git diff / commit log since the step started.
- Process state snapshot.

#### `orchestrator-finalize` — PR & Summary

Bundled as a default task at `src/wiggy/tasks/default/orchestrator-finalize/` and loaded via the standard task system (`get_task_by_name("orchestrator-finalize")`). Users can override per-project at `.wiggy/tasks/orchestrator-finalize/`. Prompt focuses on:

- Review of overall process outcome across all steps.
- PR description generation: structured format (Summary, Changes, Test Plan).
- Referencing relevant commits and key changes.
- Optionally writing a process summary to the knowledge base.

Dynamically composed per invocation with:

- Full process state (all steps and results).
- Complete git diff and commit log for the process.

### 6. Orchestrator Execution in the Process Runner

Changes to `orchestrator.py` (`run_process()`):

```
for each step in process:
    if not step.skip_orchestrator:
        run_orchestrator(phase="pre_step", step_index=i)
        decision = get_orchestrator_decision()

        if decision == "abort":
            stop process, record reason
            break

        if decision == "inject":
            insert new steps into process.steps at position i
            continue  # re-evaluate with orchestrator

    # decision == "proceed" (or skip_orchestrator)
    run step[i]
    record result

    if not step.skip_orchestrator:
        run_orchestrator(phase="post_step", step_index=i)

after all steps:
    run_orchestrator(phase="finalize")
    retrieve PR artifact
```

The orchestrator itself runs via `DockerExecutor` with:
- The same worktree as the process.
- Its own task ID.
- MCP access with the extended tool set.
- The strongest available model (see Configuration).

### 7. PR Description Generation

Replace the hardcoded PR body in `GitOperations.create_pull_request()`:

1. During the finalization phase, the orchestrator writes an artifact with template `pr_description`.
2. The process runner reads this artifact after orchestrator finalization.
3. Pass the artifact content as the `--body` argument to `gh pr create`.
4. Fallback: if no artifact is produced, use the current hardcoded string.

The orchestrator's prompt for this phase should instruct it to:
- Summarize what was done across all steps.
- Include key changes and their rationale.
- Reference relevant commits.
- Use a structured format (Summary, Changes, Test Plan).

### 8. Configuration

Add orchestrator settings to `WiggyConfig`:

```yaml
orchestrator:
  enabled: true               # default: true for processes, false for single tasks
  engine: claude               # can differ from task engine
  model: opus                  # must be the strongest model — orchestrator quality is critical
  max_injections: 3            # guard against infinite loops
  image: null                  # override docker image for orchestrator
```

Process-level override in `process.yaml`:

```yaml
orchestrator:
  enabled: true
  model: opus
  max_injections: 5
```

Per-step override in `process.yaml`:

```yaml
steps:
  - task: format
    skip_orchestrator: true    # skip pre-step and post-step orchestrator for trivial steps
  - task: implement
  - task: review
```

---

## Injection Loop Guard

To prevent infinite loops (orchestrator keeps injecting fix tasks that fail):

- Track injection count per original step.
- Hard cap via `max_injections` config (default: 3).
- After cap is reached, the orchestrator can only `proceed` or `abort`.
- Each injected step is tagged with its origin step index for traceability.

---

## Observability

- All orchestrator decisions are stored in `ProcessRun.orchestrator_decisions`.
- Orchestrator task logs are written to `.wiggy/logs/` like any other task.
- The process summary (printed at end) includes orchestrator decisions and any injected steps.
- New DB table `orchestrator_decision` for persistence across sessions.

---

## Rollout Plan

### Phase 1: Core Orchestrator Loop

- Add `get_process_state`, `set_process_decision`, `get_git_diff`, `get_commit_log` MCP tools.
- Create orchestrator task templates: `orchestrator-pre`, `orchestrator-post`, `orchestrator-finalize`.
- Modify `run_process()` to invoke orchestrator between steps.
- Make `ProcessRun.steps` mutable.
- Add `OrchestratorDecision` model and persistence.
- Add `orchestrator` config section.

### Phase 2: Step Injection

- Add `inject_steps` MCP tool.
- Implement step insertion logic in `run_process()`.
- Add injection loop guard.
- Test with review → implement remediation cycle.

### Phase 3: PR Description Generation

- Add `pr_description` artifact template.
- Finalization phase orchestrator prompt.
- Wire artifact into `GitOperations.create_pull_request()`.
- Fallback to hardcoded string when orchestrator is disabled.

### Phase 4: Polish

- Process-level orchestrator config overrides.
- Rich console output for orchestrator decisions.
- History/audit trail for orchestrator actions.
- Documentation and default prompt tuning.

---

## Resolved Decisions

1. **Orchestrator has no write access to the codebase.** It operates exclusively through dispatching task agents and producing artifacts. If a small fix is needed, the orchestrator injects a step to handle it.
2. **Pre-step and post-step are separate invocations.** Each runs in its own Docker container with a single, clear responsibility. Post-step focuses on reviewing output; pre-step focuses on planning the next action. The additional container overhead is acceptable for the clarity this provides.
3. **Orchestrator is optional per-step.** Steps can set `skip_orchestrator: true` to bypass both pre-step and post-step orchestrator invocations. Useful for trivial steps like formatting.
4. **Orchestrator uses the strongest available model.** The orchestrator makes critical supervisory decisions — reviewing quality, deciding whether to inject remediation steps, and generating PR descriptions. This requires the highest-quality model, not a cheaper alternative. Default config: `model: opus`.
