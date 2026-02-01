"""SQL schema and migrations for task history."""

import logging
from sqlite3 import Connection

log = logging.getLogger(__name__)

SCHEMA_VERSION = 5

DEFAULT_EMBEDDING_DIM = 768

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
    is_orchestrator INTEGER NOT NULL DEFAULT 0,

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

CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    content TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(key, version)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_key ON knowledge(key);
CREATE INDEX IF NOT EXISTS idx_knowledge_key_version ON knowledge(key, version DESC);

CREATE TABLE IF NOT EXISTS orchestrator_decision (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    process_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    decision TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    injected_steps TEXT,              -- JSON serialized
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task_log(task_id)
);
CREATE INDEX IF NOT EXISTS idx_orchestrator_decision_process_id
    ON orchestrator_decision(process_id);
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


VEC_TABLES = ("vec_knowledge", "vec_results", "vec_artifacts")


def _get_vec_dim(conn: Connection, table: str) -> int | None:
    """Return the embedding dimension of an existing vec0 table, or None."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    if cursor.fetchone() is None:
        return None
    # shadow column table stores the dimension info; query a row to inspect length
    try:
        row = conn.execute(f"SELECT embedding FROM {table} LIMIT 1").fetchone()
        if row is not None:
            import struct

            # vec0 stores floats as raw bytes
            return len(row[0]) // struct.calcsize("f")
    except Exception:
        pass
    # Table exists but is empty – read the schema SQL to extract the dimension
    cursor = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    sql_row = cursor.fetchone()
    if sql_row and sql_row[0]:
        import re

        m = re.search(r"float\[(\d+)]", sql_row[0])
        if m:
            return int(m.group(1))
    return None


def _ensure_vec_tables(conn: Connection, embedding_dim: int) -> None:
    """Create or recreate vec0 virtual tables with the correct dimension."""
    for table in VEC_TABLES:
        existing_dim = _get_vec_dim(conn, table)
        if existing_dim is not None and existing_dim != embedding_dim:
            log.warning(
                "Embedding dimension changed (%d -> %d), recreating %s",
                existing_dim,
                embedding_dim,
                table,
            )
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            existing_dim = None
        if existing_dim is None:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} "
                f"USING vec0(embedding float[{embedding_dim}])"
            )


def _migrate_v4_to_v5(conn: Connection) -> None:
    """Migrate schema from v4 to v5: add orchestrator support."""
    # ALTER TABLE doesn't support IF NOT EXISTS, so check first
    cursor = conn.execute("PRAGMA table_info(task_log)")
    columns = {row[1] for row in cursor.fetchall()}
    if "is_orchestrator" not in columns:
        conn.execute(
            "ALTER TABLE task_log ADD COLUMN is_orchestrator INTEGER NOT NULL DEFAULT 0"
        )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orchestrator_decision (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            process_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            step_index INTEGER NOT NULL,
            decision TEXT NOT NULL,
            reasoning TEXT NOT NULL,
            injected_steps TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES task_log(task_id)
        );
        CREATE INDEX IF NOT EXISTS idx_orchestrator_decision_process_id
            ON orchestrator_decision(process_id);
    """
    )


def _migrate_v3_to_v4(conn: Connection, embedding_dim: int) -> None:
    """Migrate schema from v3 to v4: add knowledge table and vec tables."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            content TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(key, version)
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_key
            ON knowledge(key);
        CREATE INDEX IF NOT EXISTS idx_knowledge_key_version
            ON knowledge(key, version DESC);
    """
    )
    _ensure_vec_tables(conn, embedding_dim)


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


def init_schema(conn: Connection, embedding_dim: int = DEFAULT_EMBEDDING_DIM) -> None:
    """Initialize the database schema."""
    conn.executescript(SCHEMA_SQL)
    _ensure_vec_tables(conn, embedding_dim)
    # Set initial version if not present
    cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
    if cursor.fetchone() is None:
        conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
    conn.commit()


def migrate_if_needed(
    conn: Connection, embedding_dim: int = DEFAULT_EMBEDDING_DIM
) -> None:
    """Run any pending migrations to bring schema up to date."""
    current_version = get_schema_version(conn)

    if current_version == 0:
        # Fresh install, just init
        init_schema(conn, embedding_dim)
        return

    # Apply migrations sequentially
    while current_version < SCHEMA_VERSION:
        if current_version in MIGRATIONS:
            conn.executescript(MIGRATIONS[current_version])
        elif current_version == 3:
            _migrate_v3_to_v4(conn, embedding_dim)
        elif current_version == 4:
            _migrate_v4_to_v5(conn)
        current_version += 1
        conn.execute("UPDATE schema_version SET version = ?", (current_version,))
        conn.commit()

    # Always ensure vec tables match current embedding dimensions
    _ensure_vec_tables(conn, embedding_dim)
