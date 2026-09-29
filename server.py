"""Forge 27 local server: serves index.html and keeps messages and day ticks in data.json.

Every message Arun sends is also appended to inbox.log, which the Claude Code
session tails to answer in the background.
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data.json"
INBOX = ROOT / "inbox.log"
LOCK = threading.Lock()


def load():
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return {"messages": [], "days": {}}


def save(state):
    tmp = DATA.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(DATA)


LIVE = {"active": False, "replyTo": None, "text": "", "status": ""}
WAKE = threading.Event()
START = time.mktime((2026, 9, 23, 0, 0, 0, 0, 0, -1))
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")


def today_day():
    return int((time.time() - START) // 86400) + 1


def auto_tick(state, track):
    """Studying counts: a coding or system design message ticks that track for today."""
    field = {"code": "code", "sd": "sd"}.get(track)
    if not field:
        return
    r = state.setdefault("days", {}).setdefault(time.strftime("%Y-%m-%d"), {})
    r["day"] = today_day()
    if not r.get(field):
        r[field] = True
        r.setdefault("auto", []).append(field)
        r["updatedAt"] = int(time.time() * 1000)


def transcript(messages, limit=16):
    lines = []
    for m in messages[-limit:]:
        who = "ARUN" if m["role"] == "arun" else "COACH"
        lines.append(f"--- {who} ({m.get('track', 'general')}) ---\n{m['text']}")
    return "\n\n".join(lines)


PROGRESS = ROOT / "progress.md"
READ_TOKEN = "[[READ_PROGRESS]]"
WANTS_PROGRESS = re.compile(r"progress|what (have|did) we (do|done|cover)|how am i doing|weak (spot|area)s?|my mistakes|revis|history|so far", re.I)
MODEL = "claude-sonnet-5-5"


def run_claude(prompt, system_file=None, stream=True):
    cmd = [CLAUDE, "-p", "--model", MODEL, "--effort", "low", "--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--tools", ""]
    if system_file:
        cmd += ["--append-system-prompt-file", str(system_file)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         cwd=str(ROOT), text=True, encoding="utf-8", errors="replace")
    p.stdin.write(prompt)
    p.stdin.close()
    turn_text, final = "", None
    for line in p.stdout:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "stream_event":
            e = ev.get("event", {})
            if e.get("type") == "message_start":
                turn_text = ""
            elif e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta":
                turn_text += e["delta"]["text"]
                if stream and not READ_TOKEN.startswith(turn_text.strip()[:len(READ_TOKEN)] or "x"):
                    LIVE["text"], LIVE["status"] = turn_text, ""
        elif ev.get("type") == "result":
            final = ev.get("result")
    p.wait()
    return (final or turn_text).strip()


def update_progress(state):
    """Re-summarise today's chat into its section of progress.md."""
    today = time.strftime("%Y-%m-%d")
    ms = [m for m in state["messages"] if time.strftime("%Y-%m-%d", time.localtime(m["createdAt"] / 1000)) == today]
    if not ms:
        return
    ask = ("Summarise one day of a study chat between ARUN (learner) and COACH, for the coach's long-term memory. "
           "Strictly factual, only what the transcript shows. Markdown with exactly these headings and terse bullets:\n"
           "### Solved (the coach confirmed Arun's own working solution; name the problem + approach)\n"
           "### In progress / not finished (problem + where it stopped)\n### System design covered\n"
           "### Mistakes that recurred\n### Strengths shown\nWrite '- none' for an empty section. Transcript:\n\n")
    body = "\n\n".join(("ARUN" if m["role"] == "arun" else "COACH") + ": " + m["text"][:3000] for m in ms)
    summary = run_claude(ask + body[:350000], stream=False)
    text = PROGRESS.read_text(encoding="utf-8") if PROGRESS.exists() else "# Arun's progress (Forge 27)\n"
    section = f"## {today}\n{summary}\n"
    pattern = re.compile(rf"^## {today}\n.*?(?=^## \d{{4}}-\d\d-\d\d\n|\Z)", re.S | re.M)
    text = pattern.sub(lambda _: section, text) if pattern.search(text) else text.rstrip() + "\n\n" + section
    PROGRESS.write_text(text, encoding="utf-8")


def coach_reply(state):
    latest = next((m["text"] for m in reversed(state["messages"]) if m["role"] == "arun"), "")
    if re.search(r"update (my )?progress", latest, re.I):
        LIVE["status"] = "Updating your progress file…"
        update_progress(state)
    base = (f"Today is day {today_day()} of 136 of Arun's plan.\n\n"
            "Here is the recent chat, oldest first. Reply to Arun's latest message(s):\n\n" + transcript(state["messages"]))
    with_progress = lambda: ("Arun's progress file (progress.md), for context:\n\n" + PROGRESS.read_text(encoding="utf-8")
                             + "\n\n---\n\n" + base) if PROGRESS.exists() else base
    if WANTS_PROGRESS.search(latest):
        LIVE["status"] = "Reading your progress…"
        text = run_claude(with_progress(), ROOT / "coach_prompt.md")
    else:
        text = run_claude(base, ROOT / "coach_prompt.md")
        if text.startswith(READ_TOKEN):  # the coach asked for the history itself
            LIVE.update(text="", status="Reading your progress…")
            text = run_claude(with_progress(), ROOT / "coach_prompt.md")
    return verify_outputs(text.replace(READ_TOKEN, "").strip())


PAIR = re.compile(r"```python\n(.*?)```(\s*(?:(?:\*\*)?(?:Real )?[Oo]utput:?(?:\*\*)?\s*)?)```text\n(.*?)```", re.S)


def verify_outputs(text):
    """Run every python block that is directly followed by a text block, and put the real output there."""
    def fix(m):
        code, gap, claimed = m.group(1), m.group(2), m.group(3)
        if "input(" in code or "___" in code:
            return m.group(0)
        r = run_code(code)
        real = (r["stdout"] + (("\n" + r["stderr"].strip().splitlines()[-1]) if r["stderr"].strip() else "")).strip()
        if not real or real == claimed.strip():
            return m.group(0)
        return f"```python\n{code}```{gap}```text\n{real}\n```\n*(Output corrected by running the code.)*"
    return PAIR.sub(fix, text)


def coach_worker():
    while True:
        WAKE.wait()
        WAKE.clear()
        with LOCK:
            state = load()
            waiting = [m for m in state["messages"] if m["role"] == "arun" and m.get("status") == "waiting"]
        if not waiting:
            continue
        target = waiting[-1]
        LIVE.update(active=True, replyTo=target["id"], text="", status="Thinking…")
        try:
            text = coach_reply(state)
        except Exception as exc:  # keep the worker alive; show the problem in chat
            text = f"The live coach hit an error: `{exc}`. Send your message again."
        with LOCK:
            state = load()
            ids = {m["id"] for m in waiting}
            for m in state["messages"]:
                if m["id"] in ids:
                    m["status"] = "answered"
            reply = {
                "id": uuid.uuid4().hex[:12], "role": "coach", "text": text or "(no reply)",
                "track": target.get("track", "general"), "day": target.get("day"),
                "replyTo": target["id"], "createdAt": int(time.time() * 1000),
            }
            state["messages"].append(reply)
            found = re.findall(r"```task\n(.*?)```", reply["text"], re.S)
            if found:  # the newest task card becomes the current task
                state["task"] = {"text": found[-1].strip(), "fromId": reply["id"], "updatedAt": reply["createdAt"]}
            save(state)
        LIVE.update(active=False, replyTo=None, text="", status="")
        with LOCK:
            if any(m["role"] == "arun" and m.get("status") == "waiting" for m in load()["messages"]):
                WAKE.set()


def run_code(code):
    """Run Arun's practice code with a 5-second limit; only reachable from this laptop."""
    src = ROOT / f"run_{uuid.uuid4().hex[:8]}.py"
    src.write_text(code, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(src)], capture_output=True, text=True, timeout=5,
                           cwd=str(ROOT), encoding="utf-8", errors="replace")
        return {"stdout": r.stdout[-8000:], "stderr": r.stderr[-8000:].replace(f'"{src}"', "your code"), "exit": r.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Stopped after 5 seconds. Is there an infinite loop?", "exit": -1}
    finally:
        src.unlink(missing_ok=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/live":
            self.send_json(LIVE)
        elif self.path == "/api/state":
            with LOCK:
                self.send_json(load())
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        body = self.read_body()
        if parts == ["api", "run"]:
            self.send_json(run_code(str(body.get("code", ""))))
            return
        with LOCK:
            state = load()
            if parts == ["api", "messages"]:
                msg = {
                    "id": uuid.uuid4().hex[:12],
                    "role": body.get("role", "arun"),
                    "text": str(body.get("text", "")),
                    "track": body.get("track", "general"),
                    "day": today_day(),  # the server's clock, never a stale browser tab
                    "createdAt": int(time.time() * 1000),
                }
                if body.get("replyTo"):
                    msg["replyTo"] = body["replyTo"]
                    for m in state["messages"]:
                        if m["id"] == body["replyTo"]:
                            m["status"] = "answered"
                if msg["role"] == "arun":
                    msg["status"] = "waiting"
                    auto_tick(state, msg["track"])
                state["messages"].append(msg)
                save(state)
                if msg["role"] == "arun":
                    with INBOX.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"id": msg["id"], "track": msg["track"], "day": msg["day"], "text": msg["text"]}, ensure_ascii=False) + "\n")
                    WAKE.set()
                self.send_json(msg, 201)
            elif parts == ["api", "task"]:
                state["task"] = {"text": str(body.get("text", "")), "fromId": body.get("fromId"),
                                 "updatedAt": int(time.time() * 1000)}
                save(state)
                self.send_json(state["task"])
            elif len(parts) == 3 and parts[:2] == ["api", "days"]:
                state["days"][parts[2]] = body
                save(state)
                self.send_json(body)
            else:
                self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    INBOX.touch()
    threading.Thread(target=coach_worker, daemon=True).start()
    WAKE.set()  # answer anything left waiting from before a restart
    print("Forge 27 on http://127.0.0.1:8727/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8727), Handler).serve_forever()
