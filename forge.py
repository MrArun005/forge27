"""Forge launcher: start / stop / status for the local study app. Python 3.10+, standard library only.

    python forge.py start    # start the server in the background (if not running) and open the browser
    python forge.py stop     # stop it
    python forge.py status   # is it running? where is the data?

The server keeps running after Claude Code or this terminal closes. Data lives in ~/.forge (or FORGE_DATA).
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("FORGE_PORT", "8727"))
URL = f"http://127.0.0.1:{PORT}/"


def data_dir():
    if os.environ.get("FORGE_DATA"):
        return Path(os.environ["FORGE_DATA"]).expanduser()
    if (ROOT / "data.json").exists():
        return ROOT
    return Path.home() / ".forge"


PIDFILE = data_dir() / "server.pid"


def running():
    try:
        with urllib.request.urlopen(URL + "health", timeout=1.5) as r:
            return r.status == 200
    except OSError:
        return False


def start():
    if sys.version_info < (3, 10):
        sys.exit(f"Forge needs Python 3.10 or newer (this is {sys.version.split()[0]}).")
    if running():
        print(f"Forge is already running: {URL}")
    else:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        log = open(d / "server.log", "a", encoding="utf-8")
        kw = {"cwd": str(ROOT), "stdout": log, "stderr": log, "stdin": subprocess.DEVNULL}
        if os.name == "nt":  # detached, no console window, survives the parent closing
            kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000
        else:
            kw["start_new_session"] = True
        p = subprocess.Popen([sys.executable, str(ROOT / "server.py")], **kw)
        PIDFILE.write_text(str(p.pid), encoding="utf-8")
        for _ in range(40):
            if running():
                break
            time.sleep(0.25)
        else:
            sys.exit(f"Forge didn't start. See {d / 'server.log'}")
        print(f"Forge started: {URL}  (data: {d})")
    if os.environ.get("FORGE_NO_BROWSER") != "1":
        webbrowser.open(URL)


def stop():
    pid = None
    try:
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    if not pid:
        print("No Forge server recorded as running." if not running() else
              f"Forge is running on {URL} but wasn't started by this launcher; stop it from its own terminal.")
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    PIDFILE.unlink(missing_ok=True)
    print("Forge stopped.")


def status():
    d = data_dir()
    profile = None
    try:
        profile = json.loads((d / "profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    print(json.dumps({
        "running": running(), "url": URL, "data": str(d),
        "learner": (profile or {}).get("name"), "deadline": (profile or {}).get("deadline"),
    }, indent=2))


if __name__ == "__main__":
    {"start": start, "stop": stop, "status": status}.get(sys.argv[1] if len(sys.argv) > 1 else "start", start)()
