# Chunk 04: Orchestrator Configuration Schema

## Objective

Add orchestrator configuration to `WiggyConfig`, with support for global defaults, process-level overrides, and per-step `skip_orchestrator` flag.

## Scope

**Files to modify:**

- `src/wiggy/config/schema.py` — Add `OrchestratorConfig` dataclass; add `orchestrator` field to `WiggyConfig`.
- `src/wiggy/config/loader.py` — Parse `orchestrator` section from YAML config.
- `src/wiggy/processes/base.py` — Add `skip_orchestrator: bool = False` field to `ProcessStep`; add optional `orchestrator` override to `ProcessSpec`.
- `src/wiggy/processes/loader.py` — Parse `skip_orchestrator` and process-level `orchestrator` overrides from `process.yaml`.

**Files NOT touched:** MCP server, process runner, CLI, prompt templates.

## Detailed Requirements

### 1. `OrchestratorConfig` Dataclass

Location: `src/wiggy/config/schema.py`

```python
@dataclass(frozen=True)
class OrchestratorConfig:
    enabled: bool = True
    engine: str | None = None       # defaults to process engine if None
    model: str | None = "opus"      # strongest model for supervisor
    max_injections: int = 3         # guard against infinite loops
    image: str | None = None        # override docker image
```

### 2. Global Config

In `WiggyConfig`, add:

```python
orchestrator: OrchestratorConfig = OrchestratorConfig()
```

YAML mapping in `.wiggy/config.yaml`:

```yaml
orchestrator:
  enabled: true
  engine: claude
  model: opus
  max_injections: 3
  image: null
```

### 3. Process-Level Override

In `ProcessSpec`, add an optional override:

```python
orchestrator: OrchestratorConfig | None = None  # overrides global if set
```

YAML in `process.yaml`:

```yaml
name: implement-feature
orchestrator:
  enabled: true
  model: opus
  max_injections: 5
steps:
  - task: analyse
  - task: implement
  - task: review
```

### 4. Per-Step Skip

In `ProcessStep`, add:

```python
skip_orchestrator: bool = False
```

YAML in `process.yaml`:

```yaml
steps:
  - task: format
    skip_orchestrator: true
  - task: implement
  - task: review
```

### 5. Config Resolution Order

When the process runner needs orchestrator config:

1. Start with global `WiggyConfig.orchestrator`.
2. If `ProcessSpec.orchestrator` is set, overlay its non-None fields.
3. Per-step `skip_orchestrator` is checked independently.

Add a helper function `resolve_orchestrator_config(global_config, process_spec) -> OrchestratorConfig` in the config module or processes module.

## Boundary Constraints

- Do NOT wire the config into the process runner — that is chunk 06.
- Do NOT add CLI flags for orchestrator settings.
- Do NOT create prompt templates — that is chunk 05.
- Focus purely on data structures, parsing, and resolution logic.

## Verification

- All existing tests pass.
- `mypy src/` and `ruff check src/` pass.
- New unit tests:
  - Parse orchestrator config from YAML.
  - Config resolution: global only, process override, field-level overlay.
  - `skip_orchestrator` parsed from process.yaml.
  - Missing/partial orchestrator config uses defaults.
