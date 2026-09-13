#!/bin/sh
set -eu

operation=$1
lock_dir=$2
token=$3
stale_seconds=${4:-7200}

case "$lock_dir" in
    ''|'/'|'.'|'..') echo "refusing unsafe remote lock path: $lock_dir" >&2; exit 2 ;;
esac

acquire() {
    if mkdir "$lock_dir" 2>/dev/null; then
        :
    else
        now=$(date +%s)
        started=$(cat "$lock_dir/started" 2>/dev/null || echo 0)
        case "$started" in
            ''|*[!0-9]*) started=0 ;;
        esac
        age=$((now - started))
        if test "$started" -gt 0 && test "$age" -gt "$stale_seconds"; then
            rm -rf "$lock_dir"
            mkdir "$lock_dir" 2>/dev/null || {
                echo "cloudmake remote workspace lock was acquired by another process" >&2
                exit 75
            }
            echo "cloudmake removed a stale remote workspace lock (${age}s old)" >&2
        else
            current=$(cat "$lock_dir/token" 2>/dev/null || echo unknown)
            echo "cloudmake remote workspace is busy (holder $current)" >&2
            exit 75
        fi
    fi
    printf '%s\n' "$token" > "$lock_dir/token"
    date +%s > "$lock_dir/started"
}

release() {
    current=$(cat "$lock_dir/token" 2>/dev/null || true)
    if test "$current" = "$token"; then
        rm -rf "$lock_dir"
    fi
}

case "$operation" in
    acquire) acquire ;;
    release) release ;;
    *) echo "unknown remote lock operation: $operation" >&2; exit 2 ;;
esac
