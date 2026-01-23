#!/bin/bash
set -e

READONLY_MOUNT="/mnt/credentials"
TARGET_DIR="$HOME/.claude"

log() {
    echo "[entrypoint] $*"
}

# Copy credentials if mounted and not empty
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
        log "WARNING: No credentials available. Set ANTHROPIC_API_KEY or mount credentials"
    fi
fi

exec "$@"
