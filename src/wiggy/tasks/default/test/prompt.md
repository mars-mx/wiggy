# Testing Task

You are writing and running tests to verify implementation correctness.

## Objectives

1. **Write unit tests** - Test individual functions and components
2. **Cover edge cases** - Include boundary conditions and error paths
3. **Run existing tests** - Ensure no regressions were introduced
4. **Verify behavior** - Confirm the implementation meets requirements

## Guidelines

- Follow the project's testing conventions
- Use descriptive test names that explain what is being tested
- Keep tests focused and independent
- Mock external dependencies appropriately

## Knowledge Base

Use the knowledge base to leverage and capture testing insights:

- **Before writing tests**: Call `search_knowledge` to find testing patterns, known edge cases, or constraints discovered in prior tasks
- **After testing**: Call `write_knowledge` to persist testing strategies, discovered edge cases, or coverage gaps worth tracking
  - Use descriptive keys (e.g. `testing-strategy`, `known-edge-cases`)
  - Include a clear `reason` explaining what was learned or why the strategy was chosen

## Commits

Commit each logical change individually using conventional commits:

```
<type>(<scope>): <short description>
```

Types: `test`, `fix`, `refactor`, `chore`

Examples:
- `test(auth): add unit tests for token validation`
- `fix(tests): correct flaky timeout in integration test`

Do **not** batch all changes into a single commit. Each commit should be atomic and self-contained.
