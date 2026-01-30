"""SQL schema and migrations for task history."""

from sqlite3 import Connection

SCHEMA_VERSION = 3

SCHEMA_SQL = """
-- Schema version for migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS task_log (
    task_id TEXT PRIMARY KEY,           -- 8 hex chars (wiggy-generated)
    process_id TEXT NOT NULL,           -- 8 hex chars, groups parallel executors
    executor_id INTEGER NOT NULL,

    created_at TEXT NOT NULL,           -- ISO8601 UTC
    finished_at TEXT,                   -- Nullable
    failed_at TEXT,                     -- Nullable (set if success=0)

    branch TEXT NOT NULL,               -- e.g., "wiggy/a1b2c3d4"
    worktree TEXT NOT NULL,             -- Absolute path
    main_repo TEXT NOT NULL,            -- Absolute path

    engine TEXT NOT NULL,
    model TEXT,

    -- Engine session (optional, for lookup only - currently Claude only)
    session_id TEXT,                    -- e.g., "sess_abc123..." from ClaudeParser

    task_name TEXT,                     -- TaskSpec name
    prompt TEXT,
    prompt_hash TEXT,                   -- SHA256[:16] for dedup

    total_cost REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    duration_ms INTEGER,

    success INTEGER,                    -- 0 or 1
    exit_code INTEGER,
    error_message TEXT,

    parent_id TEXT,                     -- References task_log.task_id

    FOREIGN KEY (parent_id) REFERENCES task_log(task_id)
);

-- Indexes for lookups
CREATE INDEX IF NOT EXISTS idx_session_id ON task_log(session_id)
    WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_process_id ON task_log(process_id);
CREATE INDEX IF NOT EXISTS idx_branch ON task_log(branch);
CREATE INDEX IF NOT EXISTS idx_worktree ON task_log(worktree);
CREATE INDEX IF NOT EXISTS idx_parent_id ON task_log(parent_id)
    WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_created_at ON task_log(created_at DESC);

-- Task execution results (MCP context-passing)
CREATE TABLE IF NOT EXISTS task_result (
    task_id TEXT PRIMARY KEY REFERENCES task_log(task_id) ON DELETE CASCADE,
    result_text TEXT NOT NULL,
    summary_text TEXT,
    key_files TEXT,
    tags TEXT,
    has_summary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Multiple commits per task
CREATE TABLE IF NOT EXISTS task_refs (
    task_id TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, commit_hash),
    FOREIGN KEY (task_id) REFERENCES task_log(task_id) ON DELETE CASCADE
);

-- Artifact documents per task
CREATE TABLE IF NOT EXISTS artifact (
    id TEXT PRIMARY KEY,                  -- 8 hex chars (secrets.token_hex(4))
    task_id TEXT NOT NULL REFERENCES task_log(task_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    format TEXT NOT NULL,                 -- 'json', 'markdown', 'xml', 'text'
    template_name TEXT,                   -- Template used (informational)
    tags TEXT,                            -- JSON array
    created_at TEXT NOT NULL              -- ISO8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_artifact_task_id ON artifact(task_id);
CREATE INDEX IF NOT EXISTS idx_artifact_created_at ON artifact(created_at DESC);
"""

# Migrations: key is "from_version", value is SQL to apply
MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS task_result (
        task_id TEXT PRIMARY KEY REFERENCES task_log(task_id) ON DELETE CASCADE,
        result_text TEXT NOT NULL,
        summary_text TEXT,
        key_files TEXT,
        tags TEXT,
        has_summary INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """,
    2: """
    CREATE TABLE IF NOT EXISTS artifact (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES task_log(task_id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        format TEXT NOT NULL,
        template_name TEXT,
        tags TEXT,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_artifact_task_id ON artifact(task_id);
    CREATE INDEX IF NOT EXISTS idx_artifact_created_at ON artifact(created_at DESC);
    """,
}


def get_schema_version(conn: Connection) -> int:
    """Get the current schema version from the database.

    Returns 0 if schema_version table doesn't exist or is empty.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    if cursor.fetchone() is None:
        return 0

    cursor = conn.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
    )
    row = cursor.fetchone()
    return row[0] if row else 0


def init_schema(conn: Connection) -> None:
    """Initialize the database schema."""
    conn.executescript(SCHEMA_SQL)
    # Set initial version if not present
    cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
    if cursor.fetchone() is None:
        conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
    conn.commit()


def migrate_if_needed(conn: Connection) -> None:
    """Run any pending migrations to bring schema up to date."""
    current_version = get_schema_version(conn)

    if current_version == 0:
        # Fresh install, just init
        init_schema(conn)
        return

    # Apply migrations sequentially
    while current_version < SCHEMA_VERSION:
        if current_version in MIGRATIONS:
            conn.executescript(MIGRATIONS[current_version])
        current_version += 1
        conn.execute("UPDATE schema_version SET version = ?", (current_version,))
        conn.commit()
