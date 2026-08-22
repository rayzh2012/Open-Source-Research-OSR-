#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
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
ALLOWED = {"IDLE","STATUS","GIT_SYNC","SPEED_TEST","KIMI_PROBE","KIMI_RUN"}
REMOTE_STATUS = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_STATUS.json"
REMOTE_RESULT = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_LAST_RESULT.txt"
REPO = Path.home() / "Open-Source-Research-OSR-"
MAX_PROMPT_CHARS = 16000


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
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
    log("RUN " + " ".join(cmd))
    return subprocess.run(cmd, text=True, **kwargs)


def self_update():
    try:
        remote = fetch_bytes(WATCHER_URL, 20)
        here = Path(__file__)
        local = here.read_bytes()
        if remote != local:
            tmp = here.with_suffix(".new")
            tmp.write_bytes(remote)
            os.chmod(tmp, 0o755)
            os.replace(tmp, here)
            log("SELF_UPDATE installed; next tick will use new watcher")
    except Exception as exc:
        log(f"SELF_UPDATE skipped: {exc!r}")


def publish_status(obj):
    save_json(STATUS, obj)
    rclone = shutil.which("rclone")
    if not rclone:
        raise RuntimeError("rclone not found")
    p = run([rclone, "copyto", str(STATUS), REMOTE_STATUS], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"status upload failed: {p.stderr or p.stdout}")
    if RESULT.exists():
        p = run([rclone, "copyto", str(RESULT), REMOTE_RESULT], capture_output=True)
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


def find_kimi():
    path = shutil.which("kimi")
    if path:
        return path
    for p in (
        Path.home() / ".local/bin/kimi",
        Path.home() / ".kimi/bin/kimi",
        Path("/opt/homebrew/bin/kimi"),
        Path("/usr/local/bin/kimi"),
    ):
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return None


def kimi_probe():
    found = find_kimi()
    lines = [f"kimi: {found or 'NOT_FOUND'}"]
    if found:
        p = run([found, "--version"], capture_output=True, cwd=str(REPO), timeout=60)
        lines += ["\n--version stdout:\n" + (p.stdout or ""), "\n--version stderr:\n" + (p.stderr or ""), f"returncode={p.returncode}"]
    save_result("\n".join(lines) + "\n")
    if not found:
        raise RuntimeError("Kimi CLI not found")


def kimi_run(command):
    found = find_kimi()
    if not found:
        raise RuntimeError("Kimi CLI not found")
    prompt = str(command.get("prompt", "")).strip()
    if not prompt:
        raise RuntimeError("KIMI_RUN requires a non-empty prompt")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise RuntimeError("KIMI_RUN prompt too long")
    timeout = max(30, min(int(command.get("timeout_seconds", 1800)), 7200))
    p = run([found, "-p", prompt], capture_output=True, cwd=str(REPO), timeout=timeout)
    save_result(f"KIMI_RUN\nreturncode={p.returncode}\ncwd={REPO}\n\nSTDOUT\n{p.stdout or ''}\n\nSTDERR\n{p.stderr or ''}")
    if p.returncode:
        raise RuntimeError(f"Kimi exited {p.returncode}")


def main():
    self_update()
    state = load_json(STATE, {"last_id": 0})
    cmd = fetch_json(COMMAND_URL)
    cid = int(cmd.get("id", 0))
    action = str(cmd.get("action", "IDLE")).upper()
    if action not in ALLOWED:
        raise RuntimeError(f"Refusing unapproved action: {action}")
    if cid <= int(state.get("last_id", 0)):
        return 0
    state.update({"last_id": cid, "last_action": action})
    save_json(STATE, state)
    status = {"command_id": cid, "action": action, "status": "RUNNING", "host": os.uname().nodename, "started_unix": time.time()}
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
        return 0
    except Exception as exc:
        status.update({"status": "FAILED", "error": repr(exc), "finished_unix": time.time()})
        try:
            publish_status(status)
        finally:
            log(f"FAILED command={cid} action={action} error={exc!r}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
