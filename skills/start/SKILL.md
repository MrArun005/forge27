---
name: start
description: Start the Forge interview-prep coach (a local web app) and open it in the browser. Use when the user wants to study DSA or system design with Forge, open Forge, or start their coaching session.
argument-hint: "[status]"
allowed-tools: Bash, PowerShell
---

# Start Forge

Forge is a local study app. Its launcher starts the server in the background (it keeps running after this session ends) and opens the browser.

1. Find a Python 3.10+ interpreter: try `python3 --version`, then `python --version`, then `uv run --no-project python --version`. Use the first that reports 3.10 or newer. If none does, tell the user Forge needs Python 3.10+ and stop.
2. If the user passed `status`, run `<python> "${CLAUDE_PLUGIN_ROOT}/forge.py" status` and report the result in plain words. Stop there.
3. Otherwise run `<python> "${CLAUDE_PLUGIN_ROOT}/forge.py" start`.
4. Tell the user, briefly:
   - the URL it printed (normally http://127.0.0.1:8727/)
   - on first open there's a one-minute setup form; after that the coach greets them
   - their study data lives in the folder it printed (normally `~/.forge`), which survives plugin updates and uninstalls
   - the coach runs on their own Claude Code login, so replies count against their Claude plan
   - `/forge:stop` stops the server
If the launcher printed an error, show it and suggest checking the `server.log` file in the data folder.
