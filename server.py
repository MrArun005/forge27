"""Forge: a local DSA + system design study app with a live AI coach.

Serves index.html, keeps chat, ticks, mastery tracker and progress in a data folder, runs and traces
the learner's Python, measures Big-O, and answers chat messages through the Claude Code CLI.

Code lives next to this file. Data lives in FORGE_DATA, or next to this file if a data.json is already
there (older installs), or in ~/.forge.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def pick_data_dir():
    if os.environ.get("FORGE_DATA"):
        return Path(os.environ["FORGE_DATA"]).expanduser()
    if (ROOT / "data.json").exists():  # older single-folder install
        return ROOT
    return Path.home() / ".forge"


DATA_DIR = pick_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA = DATA_DIR / "data.json"
PROFILE = DATA_DIR / "profile.json"
PROGRESS = DATA_DIR / "progress.md"
QUALITY_LOG = DATA_DIR / "coach_quality.log"
SYSTEM_FILE = DATA_DIR / "coach_system.md"
TMP = DATA_DIR / "tmp"
TMP.mkdir(exist_ok=True)
PORT = int(os.environ.get("FORGE_PORT", "8727"))
# Security: /api/run executes code, so only the Forge page may call the API. A random token (new on every
# start) is handed to the page and must come back in a custom header. Other websites can't read it, and a
# custom header forces a CORS preflight this server never approves. Host and Origin checks stop DNS rebinding.
TOKEN = uuid.uuid4().hex + uuid.uuid4().hex
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
LOCK = threading.Lock()
LIVE = {"active": False, "replyTo": None, "text": "", "status": ""}
WAKE = threading.Event()
CLAUDE = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
LEARNER = ("learner", "arun")  # "arun" is the role older installs stored
# The server may run detached with no console. On Windows, starting a console program from such a process
# pops up a new terminal window each time unless the child is created without one.
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def is_me(m):
    return m.get("role") in LEARNER


# ---------- storage ----------
def load():
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return {"messages": [], "days": {}}


def save(state):
    tmp = DATA.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(DATA)


def load_profile():
    try:
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_plan():
    return json.loads((ROOT / "plan.json").read_text(encoding="utf-8"))


def start_ts(profile=None):
    p = profile or load_profile() or {}
    try:
        return datetime.fromisoformat(p.get("start", "")).timestamp()
    except ValueError:
        return datetime.combine(date.today(), datetime.min.time()).timestamp()


def today_day():
    return int((time.time() - start_ts()) // 86400) + 1


def total_days(profile):
    try:
        return (date.fromisoformat(profile["deadline"]) - date.fromisoformat(profile["start"])).days + 1
    except (KeyError, ValueError):
        return 0


def plan_today(profile):
    """Where the learner is in the plan: the plan's weeks are stretched or squeezed onto their own timeline."""
    plan = load_plan()
    weeks, n_days = plan["weeks"], max(7, total_days(profile))
    n_weeks = -(-n_days // 7)
    day = max(1, min(n_days, today_day()))
    week = min(n_weeks, -(-day // 7))
    idx = min(len(weeks) - 1, (week - 1) * len(weeks) // n_weeks)
    coding, sd = weeks[idx]
    first = plan.get("firstWeekProblems", [])
    problem = first[(day - 1) % 7] if idx == 0 and len(first) >= 7 else None
    return (f"Plan for this week (week {week} of {n_weeks}): coding: {coding}"
            + (f" (today's suggested problem: {problem})" if problem else "")
            + f"; system design: {', '.join(sd)}.\n")


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


# ---------- mastery tracker: seen -> solved -> mastered, with spaced re-solves ----------
STATUS_BLOCK = re.compile(r"```status\n(.*?)```", re.S)


def day_str(offset=0):
    return time.strftime("%Y-%m-%d", time.localtime(time.time() + offset * 86400))


def apply_status(state, block):
    """Parse a coach ```status block (problem: X / result: seen|solved|resolved|failed) and update the tracker."""
    fields = dict(re.findall(r"^\s*(\w+)\s*:\s*(.+?)\s*$", block, re.M))
    name, result = fields.get("problem", "").strip(), fields.get("result", "").strip().lower()
    if not name or result not in ("seen", "solved", "resolved", "failed"):
        return
    probs = state.setdefault("problems", {})
    key = next((k for k in probs if k.lower() == name.lower()), name)
    p = probs.setdefault(key, {"status": "seen", "reviews": []})
    now = int(time.time() * 1000)
    if result == "solved" and p["status"] == "seen":
        p.update(status="solved", solvedAt=now, due=day_str(1))
    elif result == "resolved":
        p["reviews"].append({"at": now, "ok": True})
        if p["status"] == "seen":  # a cold solve with no earlier solve still counts as the first solve
            p.update(status="solved", solvedAt=now, due=day_str(1))
        else:
            wins = sum(1 for r in p["reviews"] if r["ok"])
            old_enough = now - p.get("solvedAt", now) >= 3 * 86400 * 1000
            if wins >= 2 and old_enough:
                p.update(status="mastered", due=day_str(21))
            else:
                p["due"] = day_str(3 if wins == 1 else 7)
    elif result == "failed":
        p["reviews"].append({"at": now, "ok": False})
        if p["status"] == "mastered":
            p["status"] = "solved"
        p["due"] = day_str(1)
    p["updatedAt"] = now


def tracker_line(state):
    probs = state.get("problems", {})
    if not probs:
        return ""
    today = day_str()
    due = [k for k, p in probs.items() if p["status"] != "seen" and p.get("due", "9") <= today]
    by = lambda s: [k for k, p in probs.items() if p["status"] == s]
    return (f"Tracker: due for a cold re-solve today: {', '.join(due) or 'none'}. "
            f"Solved: {', '.join(by('solved')) or 'none'}. Mastered: {', '.join(by('mastered')) or 'none'}. "
            f"Seen with heavy help (not solved yet): {', '.join(by('seen')) or 'none'}.\n\n")


# ---------- running, tracing and measuring the learner's code ----------
def _run_tool(args, code, timeout, fallback):
    src = TMP / f"run_{uuid.uuid4().hex[:8]}.py"
    src.write_text(code, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, *args, str(src)], capture_output=True, text=True, timeout=timeout,
                           cwd=str(TMP), encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        return r, src
    except subprocess.TimeoutExpired:
        return None, src
    finally:
        pass


def run_code(code):
    """Run practice code with a 5-second limit; the server only listens on this machine."""
    r, src = _run_tool([], code, 5, None)
    try:
        if r is None:
            return {"stdout": "", "stderr": "Stopped after 5 seconds. Is there an infinite loop?", "exit": -1}
        return {"stdout": r.stdout[-8000:], "stderr": r.stderr[-8000:].replace(f'"{src}"', "your code"), "exit": r.returncode}
    finally:
        src.unlink(missing_ok=True)


def trace_code(code):
    r, src = _run_tool([str(ROOT / "tracer.py")], code, 5, None)
    try:
        if r is None:
            return {"steps": [], "error": "Stopped after 5 seconds. Is there an infinite loop?"}
        return json.loads(r.stdout or '{"steps": [], "error": "The tracer produced no output."}')
    except ValueError:
        return {"steps": [], "error": "Couldn't read the trace."}
    finally:
        src.unlink(missing_ok=True)


def measure_code(code):
    """Empirical Big-O (complexity.py): lines executed + a stopwatch for time, peak memory for space."""
    r, src = _run_tool([str(ROOT / "complexity.py")], code, 20, None)
    try:
        if r is None:
            return {"ok": False, "error": "Measuring took over 20 seconds. Is there an infinite loop?"}
        return json.loads(r.stdout or '{"ok": false, "error": "The measurement produced no output."}')
    except ValueError:
        return {"ok": False, "error": "Couldn't read the measurement."}
    finally:
        src.unlink(missing_ok=True)


# ---------- the coach ----------
READ_TOKEN = "[[READ_PROGRESS]]"
WANTS_PROGRESS = re.compile(r"progress|what (have|did) we (do|done|cover)|how am i doing|weak (spot|area)s?|my mistakes|revis|history|so far", re.I)
SESSION_GAP = 3 * 3600 * 1000  # a gap this long since the learner's previous message starts a new session
LONG_REPLY = 300               # prose words (code and tables excluded) that trigger one shortening pass


def learner_name():
    return (load_profile() or {}).get("name") or "the learner"


def build_system_file():
    """coach_rules.md (shared) + an About-the-learner section from profile.json (private)."""
    p = load_profile() or {}
    rules = (ROOT / "coach_rules.md").read_text(encoding="utf-8")
    plan = load_plan()
    weak = "\n".join(f"- {w}" for w in p.get("weakSpots", [])) or "- none recorded yet"
    left = ""
    try:
        left = f" ({(date.fromisoformat(p['deadline']) - date.today()).days} days left)"
    except (KeyError, ValueError):
        pass
    about = f"""

## About the learner
- **Name:** {p.get('name', 'the learner')}
- **Goal:** {p.get('goal', 'interview preparation')}, deadline **{p.get('deadline', 'not set')}**{left}
- **Interview language:** {p.get('language', 'Python')} (the app's runner, tracer and Big-O check run Python)
- **Already knows:** {p.get('knows', 'not stated')}
- **Daily time:** {p.get('hours', 'not stated')}
- **Level:** {p.get('level', 'not stated')}
- **Plan:** {plan['name']}. Coding follows {plan['coding']}; system design follows Hello Interview's free guides and Alex Xu's chapters.
- **Notes:** {p.get('notes', '')}

### Weak spots to watch
{weak}
"""
    SYSTEM_FILE.write_text(rules + about, encoding="utf-8")
    return SYSTEM_FILE


def transcript(messages, limit=16):
    name = learner_name().upper()
    return "\n\n".join(f"--- {name if is_me(m) else 'COACH'} ({m.get('track', 'general')}) ---\n{m['text']}"
                       for m in messages[-limit:])


def model():
    return os.environ.get("FORGE_MODEL") or (load_profile() or {}).get("model") or "sonnet"


def run_claude(prompt, system_file=None, stream=True):
    cmd = [CLAUDE, "-p", "--model", model(), "--effort", "low", "--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--tools", ""]
    if system_file:
        cmd += ["--append-system-prompt-file", str(system_file)]
    err_file = TMP / f"claude_err_{uuid.uuid4().hex[:6]}.txt"
    with err_file.open("w", encoding="utf-8") as err:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                             cwd=str(TMP), text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        p.stdin.write(prompt)
        p.stdin.close()
        result = _read_stream(p, stream)
        p.wait()
    errors = err_file.read_text(encoding="utf-8", errors="replace").strip()
    err_file.unlink(missing_ok=True)
    if not result:
        # surface the real reason instead of a silent "(no reply)"
        useful = "\n".join(l for l in errors.splitlines() if "model catalog" not in l and "unrecognized_model" not in l)
        print(f"[coach] claude exited {p.returncode} with no reply. stderr:\n{errors[-2000:]}", flush=True)
        raise RuntimeError((useful or errors or f"claude exited with code {p.returncode} and no output")[-400:])
    return result


def _read_stream(p, stream):
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
    return (final or turn_text).strip()


def update_progress(state):
    """Re-summarise today's chat into its section of progress.md."""
    today = time.strftime("%Y-%m-%d")
    ms = [m for m in state["messages"] if time.strftime("%Y-%m-%d", time.localtime(m["createdAt"] / 1000)) == today]
    if not ms:
        return
    name = learner_name()
    ask = (f"Summarise one day of a study chat between {name.upper()} (learner) and COACH, for the coach's long-term memory. "
           "Strictly factual, only what the transcript shows. Markdown with exactly these headings and terse bullets:\n"
           f"### Solved (the coach confirmed {name}'s own working solution; name the problem + approach)\n"
           "### In progress / not finished (problem + where it stopped)\n### System design covered\n"
           "### Mistakes that recurred\n### Strengths shown\nWrite '- none' for an empty section. Transcript:\n\n")
    body = "\n\n".join((name.upper() if is_me(m) else "COACH") + ": " + m["text"][:3000] for m in ms)
    summary = run_claude(ask + body[:350000], stream=False)
    text = PROGRESS.read_text(encoding="utf-8") if PROGRESS.exists() else f"# {name}'s progress (Forge)\n"
    section = f"## {today}\n{summary}\n"
    pattern = re.compile(rf"^## {today}\n.*?(?=^## \d{{4}}-\d\d-\d\d\n|\Z)", re.S | re.M)
    text = pattern.sub(lambda _: section, text) if pattern.search(text) else text.rstrip() + "\n\n" + section
    PROGRESS.write_text(text, encoding="utf-8")


def prose_words(text):
    """Words outside code fences and table rows: what the length rule is about."""
    prose = re.sub(r"```.*?```", " ", text, flags=re.S)
    prose = "\n".join(l for l in prose.splitlines() if not l.strip().startswith("|"))
    return len(prose.split())


def is_session_start(state):
    mine = [m for m in state["messages"] if is_me(m)]
    if len(mine) < 2:
        return True
    return mine[-1].get("createdAt", 0) - mine[-2].get("createdAt", 0) >= SESSION_GAP


def log_quality(text, session_start, shortened):
    try:
        last = text.rstrip().splitlines()[-1] if text.strip() else ""
        with QUALITY_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": int(time.time() * 1000), "words": prose_words(text),
                                "ends_bold": last.strip().startswith("**") and last.strip().endswith(("**", "**?", "?**")),
                                "session_start": session_start, "shortened": shortened}) + "\n")
    except OSError:
        pass


def coach_reply(state):
    latest = next((m["text"] for m in reversed(state["messages"]) if is_me(m)), "")
    if re.search(r"update (my )?progress", latest, re.I):
        LIVE["status"] = "Updating your progress file…"
        update_progress(state)
    system = build_system_file()
    profile = load_profile() or {}
    name = learner_name()
    session_start = is_session_start(state)
    base = (f"Today is day {today_day()} of {total_days(profile) or '?'} of {name}'s plan.\n" + plan_today(profile) + tracker_line(state) +
            (f"SESSION START: {name} is back after a break. Follow rule 9.\n\n" if session_start else "") +
            f"Here is the recent chat, oldest first. Reply to {name}'s latest message(s):\n\n" + transcript(state["messages"]))
    with_progress = lambda: (f"{name}'s progress file (progress.md), for context:\n\n" + PROGRESS.read_text(encoding="utf-8")
                             + "\n\n---\n\n" + base) if PROGRESS.exists() else base
    if session_start or WANTS_PROGRESS.search(latest):
        LIVE["status"] = "Reading your progress…"
        text = run_claude(with_progress(), system)
    else:
        text = run_claude(base, system)
        if text.startswith(READ_TOKEN):  # the coach asked for the history itself
            LIVE.update(text="", status="Reading your progress…")
            text = run_claude(with_progress(), system)
    text = text.replace(READ_TOKEN, "").strip()
    shortened = False
    if prose_words(text) > LONG_REPLY:  # one guarded shortening pass, only for runaway replies
        LIVE["status"] = "Tightening the reply…"
        try:
            short = run_claude("Shorten this coaching reply to about 120 words of prose. Keep every code block, "
                               "task block and status block exactly as they are. Keep the marking (✅/❌) and end with "
                               "exactly one bolded question. Output only the shortened reply.\n\n" + text, system)
        except RuntimeError:
            short = ""  # keep the long reply rather than lose it
        if short and prose_words(short) < prose_words(text):
            text, shortened = short, True
    log_quality(text, session_start, shortened)
    return verify_outputs(text)


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
        if not load_profile():
            continue  # no coaching until onboarding is done
        with LOCK:
            state = load()
            waiting = [m for m in state["messages"] if is_me(m) and m.get("status") == "waiting"]
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
            for block in STATUS_BLOCK.findall(reply["text"]):
                apply_status(state, block)
            found = re.findall(r"```task\n(.*?)```", reply["text"], re.S)
            if found:  # the newest task card becomes the current task
                state["task"] = {"text": found[-1].strip(), "fromId": reply["id"], "updatedAt": reply["createdAt"]}
            save(state)
        LIVE.update(active=False, replyTo=None, text="", status="")
        with LOCK:
            if any(is_me(m) and m.get("status") == "waiting" for m in load()["messages"]):
                WAKE.set()


# ---------- HTTP ----------
def page_config():
    return {"profile": load_profile(), "plan": load_plan(), "port": PORT, "token": TOKEN}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def allowed(self, api):
        """Reject anything that isn't the Forge page talking to its own server."""
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/") not in {f"http://{h}" for h in ALLOWED_HOSTS}:
            return False
        if api and self.headers.get("X-Forge-Token") != TOKEN:
            return False
        return True

    def deny(self):
        self.send_json({"error": "forbidden"}, 403)

    def do_OPTIONS(self):  # never approve cross-origin preflights
        self.deny()

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
        if not self.allowed(api=self.path.startswith("/api/")):
            return self.deny()
        if self.path == "/health":  # for the launcher; reveals nothing
            return self.send_json({"ok": True, "app": "forge"})
        if self.path in ("/", "/index.html"):
            html = (ROOT / "index.html").read_text(encoding="utf-8")
            cfg = json.dumps(page_config(), ensure_ascii=False).replace("</", "<\\/")
            body = html.replace("/*FORGE_CONFIG*/null", cfg, 1).encode("utf-8")
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
        elif self.path == "/api/profile":
            self.send_json(load_profile() or {})
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.allowed(api=True) or not self.headers.get("Content-Type", "").startswith("application/json"):
            return self.deny()
        parts = self.path.strip("/").split("/")
        body = self.read_body()
        if parts == ["api", "run"]:
            return self.send_json(run_code(str(body.get("code", ""))))
        if parts == ["api", "trace"]:
            return self.send_json(trace_code(str(body.get("code", ""))))
        if parts == ["api", "complexity"]:
            return self.send_json(measure_code(str(body.get("code", ""))))
        if parts == ["api", "profile"]:
            return self.send_json(save_profile(body))
        with LOCK:
            state = load()
            if parts == ["api", "messages"]:
                role = "learner" if body.get("role", "learner") in LEARNER else str(body.get("role"))
                msg = {
                    "id": uuid.uuid4().hex[:12], "role": role, "text": str(body.get("text", "")),
                    "track": body.get("track", "general"),
                    "day": today_day(),  # the server's clock, never a stale browser tab
                    "createdAt": int(time.time() * 1000),
                }
                if body.get("replyTo"):
                    msg["replyTo"] = body["replyTo"]
                    for m in state["messages"]:
                        if m["id"] == body["replyTo"]:
                            m["status"] = "answered"
                if is_me(msg):
                    msg["status"] = "waiting"
                    auto_tick(state, msg["track"])
                state["messages"].append(msg)
                save(state)
                if is_me(msg):
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


def save_profile(body):
    """Onboarding form -> profile.json. Unknown keys are dropped; dates are validated."""
    keep = ("name", "goal", "deadlineLabel", "start", "deadline", "language", "knows", "hours", "level", "model", "notes")
    p = load_profile() or {}
    for k in keep:
        if k in body and isinstance(body[k], str):
            p[k] = body[k].strip()[:500]
    if isinstance(body.get("weakSpots"), list):
        p["weakSpots"] = [str(w).strip()[:200] for w in body["weakSpots"] if str(w).strip()][:12]
    p.setdefault("start", date.today().isoformat())
    for k in ("start", "deadline"):
        if k in p:
            try:
                date.fromisoformat(p[k])
            except ValueError:
                return {"error": f"{k} must be a date like 2027-02-05"}
    if not p.get("name") or not p.get("deadline"):
        return {"error": "name and deadline are required"}
    PROFILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def main():
    threading.Thread(target=coach_worker, daemon=True).start()
    WAKE.set()  # answer anything left waiting from before a restart
    if not shutil.which("claude") and not Path(CLAUDE).exists():
        print("Warning: the `claude` CLI wasn't found on PATH. The coach needs Claude Code installed and logged in.", flush=True)
    print(f"Forge is running on http://127.0.0.1:{PORT}/  (data: {DATA_DIR})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
