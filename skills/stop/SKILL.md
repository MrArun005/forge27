---
name: stop
description: Stop the Forge interview-prep coach's local server. Use when the user wants to stop or shut down Forge.
allowed-tools: Bash, PowerShell
---

# Stop Forge

1. Find a Python 3.10+ interpreter: try `python3 --version`, then `python --version`, then `uv run --no-project python --version`.
2. Run `<python> "${CLAUDE_PLUGIN_ROOT}/forge.py" stop` and tell the user what it printed. Their study data is not touched.
