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

**MCP tools:** Tasks with `*` tools also have access to knowledge base MCP tools
(`write_knowledge`, `get_knowledge`, `search_knowledge`, `view_knowledge_history`)
which persist decisions and learnings across tasks. Consider mentioning these in
the prompt if the task should read from or write to the knowledge base.

## Instructions

Based on the user's goal, create a new task:

1. Choose an appropriate task name (lowercase, hyphenated)
2. Determine which tools are needed (prefer minimal set)
3. Write a clear, effective prompt.md

Create the files at the target directory specified in the user's prompt.

Use the Write tool to create:
- `<target-dir>/<task-name>/task.yaml`
- `<target-dir>/<task-name>/prompt.md`
