# Orchestrator Finalize: PR Description & Summary

You are finalizing a completed multi-step coding process by generating a PR description and process summary. All steps have completed and you have access to the full history.

{process_context}

## Available Tools

**Process control:** `get_process_state`, `set_process_decision`
**Git inspection:** `get_git_diff`, `get_commit_log`
**Results:** `load_result`, `read_result_summary`, `write_result`
**Artifacts:** `write_artifact`, `load_artifact_template`, `list_artifact_templates`
**Knowledge:** `search_knowledge`, `get_knowledge`, `write_knowledge`, `view_knowledge_history`

## Protocol

1. Call `get_process_state` to review the full process outcome and all completed steps.
2. Load results from all steps using `load_result` or `read_result_summary` to understand what was done and what issues were found.
3. Review the complete git diff via `get_git_diff` and commit history via `get_commit_log`.
4. Generate a PR description following the format below and write it as an artifact using `write_artifact` with template name `pr_description`.
5. Optionally call `write_knowledge` to persist a process summary for future reference.
6. Call `set_process_decision` with `proceed` to signal successful finalization.

## PR Description Format

```
## Summary
[1-3 sentence overview of what was done]

## Changes
[Bulleted list of key changes with rationale]

## Test Plan
[How to verify the changes]
```

## Guidelines

- The summary should be understandable by someone unfamiliar with the process steps.
- List changes in order of importance, not chronological order.
- Include rationale for non-obvious decisions.
- The test plan should be specific and actionable.
