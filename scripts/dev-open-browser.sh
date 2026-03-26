#!/usr/bin/env bash
# Open the dev server in the default browser
python3 -m webbrowser http://localhost:5173 2>/dev/null ||
  xdg-open http://localhost:5173 2>/dev/null ||
  echo "Open http://localhost:5173 in your browser"
