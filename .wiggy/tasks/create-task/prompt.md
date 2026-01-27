# Create Task Specification

You are creating a new wiggy task. A task is a self-contained, reusable package of work that guides AI assistants through a specific type of task with clear boundaries and validation criteria.

## Scope

### What This Task Does
- Creates a new task directory with `task.yaml` and `prompt.md`
- Defines clear instructions for a single, focused objective
- Specifies the minimal set of tools required
- Includes validation criteria so the AI knows when it's done

### What This Task Does NOT Do
- Does not execute the created task (only creates the files)
- Does not create multi-step workflows or task chains
- Does not modify existing tasks (use a separate edit-task for that)
- Does not create tasks that require human judgment to validate completion

## Task Structure

Each task is a directory containing:

### 1. task.yaml - Metadata

```yaml
name: task-name          # lowercase, hyphenated
description: |
  One-sentence summary of what this task accomplishes.
tools:
  - Write                 # List ONLY tools the task actually needs
  - Read
model: null              # Optional: specific model preference
```

### 2. prompt.md - The Prompt Template

Every prompt.md you create MUST include these sections:

```markdown
# Task Name

Brief description of the task objective.

## Scope

### What This Task Does
- Explicit list of what the task will accomplish
- Be specific about deliverables

### What This Task Does NOT Do
- Explicit boundaries to prevent scope creep
- Things the AI should NOT attempt

## Instructions

Step-by-step guidance for completing the task.

## Validation

How to verify the task was completed correctly:
- [ ] Checklist item 1
- [ ] Checklist item 2
```

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

**Best practice:** Only include tools the task actually needs. Fewer tools = safer and more focused execution.

## Instructions

1. **Clarify the goal**: If the user's request is ambiguous, ask clarifying questions before creating the task
2. **Choose a task name**: lowercase, hyphenated (e.g., `write-tests`, `refactor-module`)
3. **Determine minimal tools**: Only include tools the task genuinely requires
4. **Write the prompt.md**: Must include Scope (Do's/Don'ts), Instructions, and Validation sections
5. **Create the files** at the target directory

## Validation

Your task creation is complete when:
- [ ] `<target-dir>/<task-name>/task.yaml` exists with valid YAML
- [ ] `<target-dir>/<task-name>/prompt.md` exists with all required sections
- [ ] The prompt includes explicit "What This Task Does" items
- [ ] The prompt includes explicit "What This Task Does NOT Do" items
- [ ] The prompt includes a Validation section with checkable criteria
- [ ] Tools list contains only what's necessary (not `*` unless truly needed)
