#!/usr/bin/env bash
# Kept for convenience; agent.py does the same thing with better output.
#   ./run_all.sh          live run (needs an API key)
#   MOCK=1 ./run_all.sh   offline demo
if [ "$MOCK" = "1" ]; then exec python3 agent.py --demo "$@"; else exec python3 agent.py "$@"; fi
