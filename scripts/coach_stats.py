"""Rate the coach from real chat data. Run from the forge27 folder:  uv run --no-project python scripts/coach_stats.py [YYYY-MM-DDTHH:MM]
Prints before/after stats around a cut-off (default: the 8-rule upgrade on 2026-09-30 13:00)."""
import datetime, json, re, sys

cut = datetime.datetime.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2026-09-30T13:00").timestamp() * 1000
ms = json.load(open("data.json", encoding="utf-8"))["messages"]
coach = [m for m in ms if m["role"] == "coach"]


def prose(t):
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    return len("\n".join(l for l in t.splitlines() if not l.strip().startswith("|")).split())


def stats(rs, label):
    n = len(rs) or 1
    count = lambda f: sum(1 for m in rs if f(m["text"]))
    ends_bold = count(lambda t: t.rstrip().splitlines()[-1].strip().startswith("**") if t.strip() else False)
    print(f"\n[{label}] replies={len(rs)}  avg prose words={sum(prose(m['text']) for m in rs)//n}")
    print(f"  full solution handed out: {count(lambda t: bool(re.search(r'```python\n(?:(?!```).)*?def ', t, re.S)) and '___' not in t)}")
    print(f"  code with blanks: {count(lambda t: '___' in t)}  |  ends with a bold line: {ends_bold} ({100*ends_bold//n}%)")
    print(f"  Q: reminders: {count(lambda t: t.startswith('Q:'))}  |  explain-back: {count(lambda t: bool(re.search(r'3 (interview )?sentences|explain.?back', t, re.I)))}")
    print(f"  status blocks: {count(lambda t: '```status' in t)}  |  step-back re-teaches: {count(lambda t: 'step back' in t.lower())}  |  session openers: {count(lambda t: 'Watch today' in t)}")


stats([m for m in coach if m["createdAt"] < cut], "before")
stats([m for m in coach if m["createdAt"] >= cut], "after")
