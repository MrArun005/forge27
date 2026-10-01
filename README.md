# Forge: an interview coach that teaches, not tells

Forge is a local web app for DSA and system design interview prep. A live AI coach runs on **your own Claude Code login**. It's built on research-based teaching: you predict before it reveals, it never hands out full solutions, and solved problems come back for spaced cold re-solves until you've mastered them.

Everything runs on your machine. Your chat, progress and code stay in `~/.forge`.

## What you get

- **A live coach** that streams its replies and follows 9 teaching rules:
  - a hint ladder instead of full solutions
  - faded worked examples
  - explain-back after every solve
  - one Peer Instruction challenge per session
  - spaced cold re-solves
  - re-teaching after two misses
  - short replies
  - a session opener that recalls your past mistakes
  - following your plan
- **A Python editor** with Tab and auto-indent, plus **Run**.
- **⏯ Trace:** step through your code line by line, with a **history table** (one row per step, one column per variable) and a **Predict mode** that hides each change until you guess it.
- **📈 Big-O:** pick your time and space guesses, then Forge measures your function on growing worst-case inputs and grades you.
- **A mastery tracker:** 🟡 seen → 🟢 solved → ✅ mastered, with cold re-solves due after 1, 3 and 7 days.
- **A Problem tab** that always shows the current task, plus pins, a plan view and a streak log.
- **A plan** that fits your deadline: NeetCode 150 in pattern order, with Hello Interview and Alex Xu for system design.

## Requirements

- **[Claude Code](https://claude.com/claude-code)**, installed and logged in. The coach calls `claude -p`, so replies count against **your** Claude plan. No API key is needed.
- **Python 3.10+**. Forge uses only the standard library, so there's nothing to `pip install`.
- Windows, macOS or Linux.

## Install as a Claude Code plugin (recommended)

```bash
claude plugin marketplace add MrArun005/forge27
claude plugin install forge@forge-coach
```

Then, in any Claude Code session:

```
/forge:start           start Forge and open it in your browser
/forge:start status    is it running? where's my data?
/forge:stop            stop the server
```

## Or run it directly

```bash
git clone https://github.com/MrArun005/forge27 forge && cd forge
python forge.py start    # opens http://127.0.0.1:8727/
python forge.py stop
```

The first time you open it, a one-minute form asks for your name, deadline, goal, current level and weak spots. The coach takes it from there.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `FORGE_DATA` | `~/.forge` | Where your chat, profile, progress and tracker live |
| `FORGE_PORT` | `8727` | Local port |
| `FORGE_MODEL` | from your profile, else `sonnet` | The Claude model the coach uses, e.g. `opus` |
| `FORGE_NO_BROWSER` | unset | Set it to `1` to stop the launcher opening a browser |

You can edit `~/.forge/profile.json` any time to change your deadline, weak spots or model.

## How it works

```
browser ──► server.py (127.0.0.1 only) ──► claude -p (your login, streaming, no tools)
               │                                 │
               ├── coach_rules.md (shared) + your profile.json → coach instructions
               ├── progress.md: daily summaries, read only when needed
               ├── tracer.py / complexity.py: trace and Big-O, run on your machine
               └── data.json: chat, ticks, tracker
```

- The coach has **no tools**. When it shows code with an output, the server runs that code and corrects the output if it's wrong.
- `progress.md` is the coach's long-term memory. It's read when you mention progress, at the start of a session, or when the coach asks for it. Say **"update progress"** to refresh today's entry.

## Security and privacy

- The server listens on **127.0.0.1 only**.
- It runs the Python you write, with your user's permissions. Only run code you'd run in a terminal.
- Every API call needs a random token that's created at each start and given only to the Forge page, so other websites can't make your Forge run code. Host and Origin checks block DNS rebinding.
- Your chat is sent to Anthropic through Claude Code, the same as any Claude Code session. Everything else stays local.

## Rate the coach

```bash
python scripts/coach_stats.py 2026-10-01T00:00
```

This prints before/after numbers from your real chat: solutions handed out, reply length, bold endings, re-teaches and session openers.

## Licence

MIT
