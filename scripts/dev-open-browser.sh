#!/usr/bin/env bash
# Open the dev server in the default browser
URL="http://localhost:5173"

if grep -qi microsoft /proc/version 2>/dev/null; then
  # WSL: use wslview (wslu) or fall back to cmd.exe
  wslview "$URL" 2>/dev/null ||
    cmd.exe /c start "" "$URL" 2>/dev/null ||
    echo "Open $URL in your browser"
else
  python3 -m webbrowser "$URL" 2>/dev/null ||
    xdg-open "$URL" 2>/dev/null ||
    echo "Open $URL in your browser"
fi
