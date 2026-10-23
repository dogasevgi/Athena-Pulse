#!/bin/bash
# Double-click to open the AI search agent in your browser.
cd "$(dirname "$0")"
echo "Starting the AI search agent..."
python3 -m pip install --user -q -r requirements.txt >/dev/null 2>&1
python3 app.py
