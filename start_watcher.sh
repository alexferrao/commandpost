#!/bin/bash
cd "$(dirname "$0")"
echo "Starting CommandPost Watcher..."
nohup uv run python watcher.py > watcher.log 2>&1 &
echo "Watcher started (PID: $!)"
echo "Logs: $(pwd)/watcher.log"
