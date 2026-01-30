# Implementation Task

You are implementing code changes for this project.

## Objectives

1. **Understand requirements** - Review what needs to be built or changed
2. **Write clean code** - Follow existing patterns and conventions
3. **Keep changes focused** - Only modify what is necessary
4. **Handle edge cases** - Consider error conditions gracefully

## Guidelines

- Match the codebase's coding style
- Use clear, descriptive names
- Add comments only where logic is not self-evident
- Avoid over-engineering or unnecessary abstractions

## Knowledge Base

Use the knowledge base to align with prior decisions and record new ones:

- **Before coding**: Call `search_knowledge` to find design decisions, API conventions, and constraints from prior analysis or review tasks
- **After implementation**: Call `write_knowledge` to persist significant decisions made during implementation — patterns chosen, technical constraints discovered, or conventions established
  - Use descriptive keys (e.g. `api-design-decisions`, `error-handling-pattern`)
  - Include a clear `reason` explaining why this decision was made

## Commits

Commit each logical change individually using conventional commits:

```
<type>(<scope>): <short description>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`, `style`, `perf`

Examples:
- `feat(auth): add JWT token refresh endpoint`
- `fix(api): handle null response from upstream service`
- `refactor(db): extract query builder into utility`

Do **not** batch all changes into a single commit. Each commit should be atomic and self-contained.
