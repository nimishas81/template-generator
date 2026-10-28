#!/usr/bin/env bash
cd "$(dirname "$0")"
PORT="${PORT:-5055}"
( sleep 1.5 && open "http://localhost:$PORT" 2>/dev/null || xdg-open "http://localhost:$PORT" 2>/dev/null ) &
exec python3 app.py
