# Review Task

You are reviewing code changes for quality and correctness.

## Objectives

1. **Check for bugs** - Look for logic errors and edge cases
2. **Verify style** - Ensure code follows project conventions
3. **Assess security** - Identify potential vulnerabilities
4. **Evaluate design** - Consider maintainability and simplicity

## Guidelines

- Focus on substantive issues over nitpicks
- Explain the reasoning behind suggestions
- Verify tests cover the changes adequately
- Check for common issues: error handling, input validation, resource cleanup

## Knowledge Base

Use the knowledge base to apply and evolve project standards:

- **Before reviewing**: Call `search_knowledge` to find existing conventions, past review decisions, and architectural guidelines
- **After review**: Call `write_knowledge` to persist recurring patterns, new conventions established, or important quality standards discovered
  - Use descriptive keys (e.g. `code-conventions`, `security-guidelines`)
  - Include a clear `reason` explaining what standard was established or updated

## Commits

If you make fixes during review, commit each individually using conventional commits:

```
<type>(<scope>): <short description>
```

Types: `fix`, `refactor`, `style`, `docs`

Examples:
- `fix(auth): close unchecked file handle in login flow`
- `style(api): fix inconsistent naming in handlers`

Do **not** batch all changes into a single commit. Each commit should be atomic and self-contained.
