# Debug Task

You are debugging an issue to identify its root cause.

## Objectives

1. **Reproduce the issue** - Confirm the bug exists and understand the symptoms
2. **Trace the code path** - Follow the execution flow to find where things go wrong
3. **Identify root cause** - Pinpoint the exact source of the failure
4. **Document findings** - Record the root cause, affected components, and proposed fix approach

## Guidelines

- Start by reproducing the issue to confirm symptoms
- Read error messages, logs, and stack traces carefully
- Use targeted debugging: add temporary print statements or run tests in isolation
- Narrow down the problem systematically — bisect the code path
- Do NOT fix the issue in this step; focus on diagnosis only
- Clean up any temporary debugging artifacts before finishing

## Knowledge Base

Use the knowledge base to build on prior analysis and share findings:

- **Before debugging**: Call `search_knowledge` to find prior analysis, known issues, or architectural context relevant to the problem area
- **After debugging**: Call `write_knowledge` to persist the root cause analysis, affected components, and recommended fix strategy
  - Use descriptive keys (e.g. `bug-root-cause`, `affected-components`)
  - Include a clear `reason` explaining what was found and why the issue occurs
