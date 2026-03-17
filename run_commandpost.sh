#!/bin/bash
cd "$(dirname "$0")"
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH
exec .venv/bin/python watcher.py
