# Forge 27

A local study app for daily DSA (in Python) and system design practice, with a live AI coach.

- **Chat coach**: replies stream in as they're written. The server runs the Claude Code CLI headless (`claude -p`, Sonnet, low effort, no tools) with `coach_prompt.md` as its instructions. It re-runs every code example and fixes any wrong output.
- **Code editor**: Tab and Shift+Tab indent and outdent, lines auto-indent after `:`, and **Run** executes Python on your machine with a 5-second limit.
- **Today panel**: day type (1 h / 2 h / 3 h+), two daily tasks, a streak strip, and a countdown to 5 Feb 2027.
- **19-week plan and streak log**: NeetCode 150 order for coding, plus Hello Interview and Alex Xu for system design.

## Run

```bash
uv run --no-project python server.py
# then open http://127.0.0.1:8727/
```

Needs Python 3.10+ (standard library only), and the `claude` CLI, logged in, for the coach.
Your data stays local in `data.json`, which git ignores.
