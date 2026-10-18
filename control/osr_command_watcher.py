#!/usr/bin/env python3
from __future__ import annotations

import hashlib
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
DRIVE_COMMAND = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_COMMAND.json"
APP = Path.home() / "Library" / "Application Support" / "OSR Control"
APP.mkdir(parents=True, exist_ok=True)
STATE = APP / "state.json"
STATUS = APP / "OSR_CONTROL_STATUS.json"
LOG = APP / "osr-control.log"
RESULT = APP / "last_result.txt"
ALLOWED = {"IDLE", "STATUS", "GIT_SYNC", "SPEED_TEST", "KIMI_PROBE", "KIMI_RUN", "RUN_REPO_TASK"}
REMOTE_STATUS = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_STATUS.json"
REMOTE_RESULT = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_LAST_RESULT.txt"
REPO = Path.home() / "Open-Source-Research-OSR-"
MAX_PROMPT_CHARS = 16000
POLL_SECONDS = 5
MAX_TASK_BYTES = 262144
MAX_TASK_TIMEOUT = 7200


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")
    os.replace(tmp, path)


def cache_bust(url: str) -> str:
    return url + ("&" if "?" in url else "?") + f"_osr_ts={time.time_ns()}"


def fetch_bytes(url: str, timeout: int = 30, max_bytes: int | None = None) -> bytes:
    curl = shutil.which("curl") or "/usr/bin/curl"
    p = subprocess.run(
        [curl, "-fsSL", "--max-time", str(timeout), "-H", "Cache-Control: no-cache", "-H", "Pragma: no-cache", cache_bust(url)],
        capture_output=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"curl fetch failed rc={p.returncode}: {(p.stderr or b'').decode('utf-8','replace')}")
    if max_bytes is not None and len(p.stdout) > max_bytes:
        raise RuntimeError(f"remote payload too large: {len(p.stdout)} > {max_bytes}")
    return p.stdout


def fetch_json(url: str):
    return json.loads(fetch_bytes(url, max_bytes=65536).decode("utf-8"))


def run(cmd: list[str], **kwargs):
    log("RUN " + " ".join(cmd[:3]) + (" ..." if len(cmd) > 3 else ""))
    return subprocess.run(cmd, text=True, **kwargs)


def find_rclone() -> str:
    path = shutil.which("rclone") or "/usr/local/bin/rclone"
    if not Path(path).exists():
        raise RuntimeError("rclone not found")
    return path


def fetch_drive_command():
    p = subprocess.run(
        [find_rclone(), "cat", DRIVE_COMMAND],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if p.returncode != 0:
        raise RuntimeError(f"Drive raw command cat failed rc={p.returncode}: {p.stderr or p.stdout}")
    raw = (p.stdout or "").encode("utf-8")
    if not raw.strip():
        raise RuntimeError("Drive raw command returned empty output")
    if len(raw) > 65536:
        raise RuntimeError(f"Drive raw command too large: {len(raw)}")
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError("Drive raw command is not a JSON object")
    return obj


def fetch_command():
    try:
        return fetch_drive_command(), "drive", ""
    except Exception as drive_exc:
        detail = repr(drive_exc)[:1600]
        try:
            return fetch_json(COMMAND_URL), "github_fallback", detail
        except Exception as github_exc:
            raise RuntimeError(f"command read failed: drive={drive_exc!r}; github={github_exc!r}")


def self_update_and_exec() -> None:
    remote = fetch_bytes(WATCHER_URL, 20, MAX_TASK_BYTES)
    here = Path(__file__)
    if remote == here.read_bytes():
        return
    tmp = here.with_suffix(".new")
    tmp.write_bytes(remote)
    os.chmod(tmp, 0o755)
    os.replace(tmp, here)
    log("SELF_UPDATE installed; restarting watcher")
    os.execv(sys.executable, [sys.executable, str(here)])


def publish_status(obj: dict) -> None:
    save_json(STATUS, obj)
    rclone = find_rclone()
    p = subprocess.run([rclone, "copyto", str(STATUS), REMOTE_STATUS], text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"status upload failed: {p.stderr or p.stdout}")
    if RESULT.exists():
        p = subprocess.run([rclone, "copyto", str(RESULT), REMOTE_RESULT], text=True, capture_output=True)
        if p.returncode != 0:
            raise RuntimeError(f"result upload failed: {p.stderr or p.stdout}")


def save_result(text: str) -> None:
    RESULT.write_text(text, "utf-8")


def git_sync() -> None:
    git = shutil.which("git") or "/usr/bin/git"
    p = run([git, "-C", str(REPO), "pull", "--ff-only"], capture_output=True)
    save_result((p.stdout or "") + (p.stderr or ""))
    if p.returncode:
        raise RuntimeError(f"git pull failed: {p.returncode}")


def speed_test() -> None:
    git_sync()
    p = run(["/bin/zsh", str(REPO / "control/OSR_LOCAL_SPEED_TEST.command")], capture_output=True)
    save_result((p.stdout or "") + (p.stderr or ""))
    if p.returncode:
        raise RuntimeError(f"speed test failed: {p.returncode}")


def kimi_probe() -> None:
    p = run(
        ["/bin/zsh", "-ilc", "printf 'kimi_path='; whence -p kimi; kimi --version"],
        capture_output=True,
        cwd=str(REPO),
        timeout=60,
    )
    save_result(f"KIMI_PROBE\nreturncode={p.returncode}\n\nSTDOUT\n{p.stdout or ''}\n\nSTDERR\n{p.stderr or ''}")
    if p.returncode:
        raise RuntimeError(f"Kimi probe exited {p.returncode}")


def kimi_run(command: dict) -> None:
    prompt = str(command.get("prompt", "")).strip()
    if not prompt:
        raise RuntimeError("KIMI_RUN requires a non-empty prompt")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise RuntimeError("KIMI_RUN prompt too long")
    timeout = max(30, min(int(command.get("timeout_seconds", 1800)), MAX_TASK_TIMEOUT))
    p = run(
        ["/bin/zsh", "-ilc", "exec kimi -p \"$1\"", "osr-kimi", prompt],
        capture_output=True,
        cwd=str(REPO),
        timeout=timeout,
    )
    save_result(f"KIMI_RUN\nreturncode={p.returncode}\ncwd={REPO}\n\nSTDOUT\n{p.stdout or ''}\n\nSTDERR\n{p.stderr or ''}")
    if p.returncode:
        raise RuntimeError(f"Kimi exited {p.returncode}")


def run_repo_task(command: dict) -> None:
    rel = str(command.get("task_path", "")).strip()
    expected = str(command.get("sha256", "")).strip().lower()
    if not rel.startswith("tools/remote_tasks/") or not rel.endswith(".py") or ".." in rel:
        raise RuntimeError("RUN_REPO_TASK path must be tools/remote_tasks/*.py")
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise RuntimeError("RUN_REPO_TASK requires a valid sha256")
    raw = fetch_bytes(RAW + "/" + rel, 60, MAX_TASK_BYTES)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise RuntimeError(f"task sha256 mismatch expected={expected} actual={actual}")
    args = command.get("args", [])
    if not isinstance(args, list) or len(args) > 32 or any(not isinstance(x, str) or len(x) > 2048 for x in args):
        raise RuntimeError("RUN_REPO_TASK args invalid")
    timeout = max(30, min(int(command.get("timeout_seconds", 1800)), MAX_TASK_TIMEOUT))
    work = APP / "runtime" / "remote_tasks"
    work.mkdir(parents=True, exist_ok=True)
    task = work / Path(rel).name
    task.write_bytes(raw)
    os.chmod(task, 0o700)
    env = os.environ.copy()
    env["OSR_REPO"] = str(REPO)
    env["OSR_REMOTE_TASK_SHA256"] = actual
    p = run([sys.executable, str(task), *args], capture_output=True, cwd=str(REPO), env=env, timeout=timeout)
    save_result(f"RUN_REPO_TASK\npath={rel}\nsha256={actual}\nreturncode={p.returncode}\n\nSTDOUT\n{p.stdout or ''}\n\nSTDERR\n{p.stderr or ''}")
    if p.returncode:
        raise RuntimeError(f"remote task exited {p.returncode}")


def process_once() -> None:
    cmd, source, source_detail = fetch_command()
    state = load_json(STATE, {"last_id": 0})
    cid = int(cmd.get("id", 0))
    action = str(cmd.get("action", "IDLE")).upper()
    if action not in ALLOWED:
        raise RuntimeError(f"Refusing unapproved action: {action}")
    if cid <= int(state.get("last_id", 0)):
        return
    state.update({"last_id": cid, "last_action": action, "last_source": source})
    save_json(STATE, state)
    status = {
        "command_id": cid,
        "action": action,
        "status": "RUNNING",
        "host": os.uname().nodename,
        "started_unix": time.time(),
        "watcher": "2.5",
        "command_source": source,
    }
    if source_detail:
        status["command_source_detail"] = source_detail
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
        elif action == "RUN_REPO_TASK":
            run_repo_task(cmd)
        elif action in {"STATUS", "IDLE"}:
            save_result(action + "\n")
        status.update({"status": "SUCCESS", "finished_unix": time.time()})
        publish_status(status)
        log(f"SUCCESS command={cid} action={action} source={source}")
    except Exception as exc:
        status.update({"status": "FAILED", "error": repr(exc), "finished_unix": time.time()})
        publish_status(status)
        log(f"FAILED command={cid} action={action} source={source} error={exc!r}")


def main() -> None:
    log("OSR watcher 2.5 persistent loop starting")
    while True:
        try:
            self_update_and_exec()
            process_once()
        except Exception as exc:
            log(f"TICK_ERROR {exc!r}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
