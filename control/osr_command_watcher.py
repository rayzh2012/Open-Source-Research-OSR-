#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BRANCH = "stage2-direct-miner-v3-1"
RAW = f"https://raw.githubusercontent.com/rayzh2012/Open-Source-Research-OSR-/{BRANCH}"
COMMAND_URL = RAW + "/control/osr_command.json"
WATCHER_URL = RAW + "/control/osr_command_watcher.py"
APP = Path.home() / "Library" / "Application Support" / "OSR Control"
APP.mkdir(parents=True, exist_ok=True)
STATE = APP / "state.json"
STATUS = APP / "OSR_CONTROL_STATUS.json"
LOG = APP / "osr-control.log"
RESULT = APP / "last_result.txt"
ALLOWED = {"IDLE", "STATUS", "GIT_SYNC", "SPEED_TEST", "KIMI_PROBE", "KIMI_RUN"}
REMOTE_STATUS = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_STATUS.json"
REMOTE_RESULT = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_LAST_RESULT.txt"
REPO = Path.home() / "Open-Source-Research-OSR-"
MAX_PROMPT_CHARS = 16000
POLL_SECONDS = 5


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")
    os.replace(tmp, path)


def cache_bust(url):
    return url + ("&" if "?" in url else "?") + f"_osr_ts={time.time_ns()}"


def fetch_bytes(url, timeout=30):
    curl = shutil.which("curl") or "/usr/bin/curl"
    p = subprocess.run(
        [curl, "-fsSL", "--max-time", str(timeout), "-H", "Cache-Control: no-cache", "-H", "Pragma: no-cache", cache_bust(url)],
        capture_output=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"curl fetch failed rc={p.returncode}: {(p.stderr or b'').decode('utf-8','replace')}")
    return p.stdout


def fetch_json(url):
    return json.loads(fetch_bytes(url).decode("utf-8"))


def run(cmd, **kwargs):
    log("RUN " + " ".join(cmd[:3]) + (" ..." if len(cmd) > 3 else ""))
    return subprocess.run(cmd, text=True, **kwargs)


def self_update_and_exec():
    remote = fetch_bytes(WATCHER_URL, 20)
    here = Path(__file__)
    if remote == here.read_bytes():
        return
    tmp = here.with_suffix(".new")
    tmp.write_bytes(remote)
    os.chmod(tmp, 0o755)
    os.replace(tmp, here)
    log("SELF_UPDATE installed; restarting watcher")
    os.execv(sys.executable, [sys.executable, str(here)])


def publish_status(obj):
    save_json(STATUS, obj)
    rclone = shutil.which("rclone")
    if not rclone:
        raise RuntimeError("rclone not found")
    p = subprocess.run([rclone, "copyto", str(STATUS), REMOTE_STATUS], text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"status upload failed: {p.stderr or p.stdout}")
    if RESULT.exists():
        p = subprocess.run([rclone, "copyto", str(RESULT), REMOTE_RESULT], text=True, capture_output=True)
        if p.returncode != 0:
            raise RuntimeError(f"result upload failed: {p.stderr or p.stdout}")


def save_result(text):
    RESULT.write_text(text, "utf-8")


def git_sync():
    git = shutil.which("git") or "/usr/bin/git"
    p = run([git, "-C", str(REPO), "pull", "--ff-only"], capture_output=True)
    save_result((p.stdout or "") + (p.stderr or ""))
    if p.returncode:
        raise RuntimeError(f"git pull failed: {p.returncode}")


def speed_test():
    git_sync()
    p = run(["/bin/zsh", str(REPO / "control/OSR_LOCAL_SPEED_TEST.command")], capture_output=True)
    save_result((p.stdout or "") + (p.stderr or ""))
    if p.returncode:
        raise RuntimeError(f"speed test failed: {p.returncode}")


def kimi_probe():
    p = run(
        ["/bin/zsh", "-ilc", "printf 'kimi_path='; whence -p kimi; kimi --version"],
        capture_output=True,
        cwd=str(REPO),
        timeout=60,
    )
    save_result(f"KIMI_PROBE\nreturncode={p.returncode}\n\nSTDOUT\n{p.stdout or ''}\n\nSTDERR\n{p.stderr or ''}")
    if p.returncode:
        raise RuntimeError(f"Kimi probe exited {p.returncode}")


def kimi_run(command):
    prompt = str(command.get("prompt", "")).strip()
    if not prompt:
        raise RuntimeError("KIMI_RUN requires a non-empty prompt")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise RuntimeError("KIMI_RUN prompt too long")
    timeout = max(30, min(int(command.get("timeout_seconds", 1800)), 7200))
    p = run(
        ["/bin/zsh", "-ilc", "exec kimi -p \"$1\"", "osr-kimi", prompt],
        capture_output=True,
        cwd=str(REPO),
        timeout=timeout,
    )
    save_result(f"KIMI_RUN\nreturncode={p.returncode}\ncwd={REPO}\n\nSTDOUT\n{p.stdout or ''}\n\nSTDERR\n{p.stderr or ''}")
    if p.returncode:
        raise RuntimeError(f"Kimi exited {p.returncode}")


def process_once():
    cmd = fetch_json(COMMAND_URL)
    state = load_json(STATE, {"last_id": 0})
    cid = int(cmd.get("id", 0))
    action = str(cmd.get("action", "IDLE")).upper()
    if action not in ALLOWED:
        raise RuntimeError(f"Refusing unapproved action: {action}")
    if cid <= int(state.get("last_id", 0)):
        return
    state.update({"last_id": cid, "last_action": action})
    save_json(STATE, state)
    status = {"command_id": cid, "action": action, "status": "RUNNING", "host": os.uname().nodename, "started_unix": time.time(), "watcher": "2.0"}
    publish_status(status)
    try:
        if action == "GIT_SYNC":
            git_sync()
        elif action == "SPEED_TEST":
            speed_test()
        elif action == "KIMI_PROBE":
            kimi_probe()
        elif action == "KIMI_RUN":
            kimi_run(cmd)
        elif action in {"STATUS", "IDLE"}:
            save_result(action + "\n")
        status.update({"status": "SUCCESS", "finished_unix": time.time()})
        publish_status(status)
        log(f"SUCCESS command={cid} action={action}")
    except Exception as exc:
        status.update({"status": "FAILED", "error": repr(exc), "finished_unix": time.time()})
        publish_status(status)
        log(f"FAILED command={cid} action={action} error={exc!r}")


def main():
    log("OSR watcher 2.0 persistent loop starting")
    while True:
        try:
            self_update_and_exec()
            process_once()
        except Exception as exc:
            log(f"TICK_ERROR {exc!r}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
