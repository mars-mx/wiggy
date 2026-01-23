#!/bin/bash
set -e

READONLY_MOUNT="/mnt/credentials"
TARGET_DIR="$HOME/.claude"

# Output JSON log message for wiggy parser
log() {
    printf '{"type":"wiggy_log","message":"%s"}\n' "$1"
}

# Output JSON error message
log_error() {
    printf '{"type":"wiggy_error","message":"%s"}\n' "$1"
}

# Copy credentials if mounted and not empty.
# We do this at runtime so we can modify the config at runtime without modifying the outside credentials.
if [ -d "$READONLY_MOUNT" ] && [ "$(ls -A "$READONLY_MOUNT" 2>/dev/null)" ]; then
    log "Found mounted credentials at $READONLY_MOUNT"
    mkdir -p "$TARGET_DIR"
    cp -a "$READONLY_MOUNT/." "$TARGET_DIR/"
    chmod -R u+rw "$TARGET_DIR"
    log "Copied credentials to $TARGET_DIR"
else
    log "No mounted credentials found at $READONLY_MOUNT"
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        log "ANTHROPIC_API_KEY environment variable is set"
    else
        log_error "WARNING: No credentials available. Set ANTHROPIC_API_KEY or mount credentials"
    fi
fi

exec "$@"
