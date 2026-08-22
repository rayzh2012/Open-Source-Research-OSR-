#!/usr/bin/env python3
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BRANCH = "stage2-direct-miner-v3-1"
RAW = f"https://raw.githubusercontent.com/rayzh2012/Open-Source-Research-OSR-/{BRANCH}"
COMMAND_URL = RAW + "/control/osr_command.json"
APP = Path.home() / "Library" / "Application Support" / "OSR Control"
APP.mkdir(parents=True, exist_ok=True)
STATE = APP / "state.json"
STATUS = APP / "OSR_CONTROL_STATUS.json"
LOG = APP / "osr-control.log"
RESULT = APP / "last_result.txt"
ALLOWED = {
    "IDLE",
    "STATUS",
    "GIT_SYNC",
    "SPEED_TEST",
    "KIMI_PROBE",
    "STAGE1_PREFLIGHT",
}
REMOTE_STATUS = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_STATUS.json"
REMOTE_RESULT = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_LAST_RESULT.txt"
REPO = Path.home() / "Open-Source-Research-OSR-"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
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


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "osr-command-watcher/1.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url: str, path: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "osr-command-watcher/1.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        path.write_bytes(r.read())


def run(cmd: list[str], **kwargs):
    log("RUN " + " ".join(cmd))
    return subprocess.run(cmd, text=True, **kwargs)


def discover_drive_root() -> Path:
    env = os.environ.get("OSR_DRIVE_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    candidates = [Path("/content/drive/MyDrive")]
    for pat in (
        str(Path.home() / "Library/CloudStorage/GoogleDrive-*/My Drive"),
        str(Path.home() / "Library/CloudStorage/GoogleDrive-*/MyDrive"),
        str(Path.home() / "Google Drive/My Drive"),
        str(Path.home() / "Google Drive"),
    ):
        candidates.extend(Path(p) for p in glob.glob(pat))
    for p in candidates:
        try:
            if p.is_dir():
                return p
        except OSError:
            pass
    raise RuntimeError("No usable local Google Drive filesystem found")


def publish_status(obj: dict) -> None:
    save_json(STATUS, obj)
    if shutil.which("rclone"):
        run(["rclone", "copyto", str(STATUS), REMOTE_STATUS], capture_output=True)
        if RESULT.exists():
            run(["rclone", "copyto", str(RESULT), REMOTE_RESULT], capture_output=True)


def save_result(text: str) -> None:
    RESULT.write_text(text, "utf-8")


def git_sync() -> None:
    if not (REPO / ".git").is_dir():
        raise RuntimeError(f"repo missing: {REPO}")
    p = run(["git", "-C", str(REPO), "pull", "--ff-only"], capture_output=True)
    save_result((p.stdout or "") + (p.stderr or ""))
    if p.returncode != 0:
        raise RuntimeError(f"git pull failed: {p.returncode}")


def speed_test() -> None:
    git_sync()
    script = REPO / "control" / "OSR_LOCAL_SPEED_TEST.command"
    p = run(["/bin/zsh", str(script)], capture_output=True)
    save_result((p.stdout or "") + (p.stderr or ""))
    if p.returncode != 0:
        raise RuntimeError(f"speed test failed: {p.returncode}")


def kimi_probe() -> None:
    names = ["kimi", "kimi-code", "kimitool", "k2"]
    lines = []
    found = None
    for name in names:
        path = shutil.which(name)
        lines.append(f"{name}: {path or 'NOT_FOUND'}")
        if path and found is None:
            found = path
    if found:
        p = run([found, "--version"], capture_output=True)
        lines.append("\n--version stdout:\n" + (p.stdout or ""))
        lines.append("\n--version stderr:\n" + (p.stderr or ""))
        lines.append(f"returncode={p.returncode}")
    else:
        lines.append("\nNo known Kimi CLI executable found on PATH.")
    save_result("\n".join(lines) + "\n")


def stage1_preflight(command_id: int) -> None:
    drive = discover_drive_root()
    work = APP / "runtime"
    work.mkdir(parents=True, exist_ok=True)
    stage1 = work / "osr_stage1_identity_lock_v3.py"
    preflight = work / "osr_stage2_preflight_v1.py"
    download(RAW + "/tools/osr_stage1_identity_lock_v3.py", stage1)
    download(RAW + "/tools/osr_stage2_preflight_v1.py", preflight)
    out_dir = drive / "OSR_WORK_SPACE" / "Stage1_Identity_v3"
    env = os.environ.copy()
    env["OSR_DRIVE_ROOT"] = str(drive)
    env["OSR_WORKSPACE"] = str(drive / "OSR_WORK_SPACE")
    p1 = run([sys.executable, str(stage1), "--drive-root", str(drive), "--out-dir", str(out_dir)], env=env, capture_output=True)
    text = (p1.stdout or "") + (p1.stderr or "")
    if p1.returncode != 0:
        save_result(text)
        raise RuntimeError(f"Stage-1 v3 failed with exit {p1.returncode}")
    p2 = run([sys.executable, str(preflight)], env=env, capture_output=True)
    text += "\n" + (p2.stdout or "") + (p2.stderr or "")
    save_result(text)
    if p2.returncode != 0:
        raise RuntimeError(f"Stage-2 preflight failed with exit {p2.returncode}")


def main() -> int:
    state = load_json(STATE, {"last_id": 0})
    cmd = fetch_json(COMMAND_URL)
    command_id = int(cmd.get("id", 0))
    action = str(cmd.get("action", "IDLE")).upper()
    if action not in ALLOWED:
        raise RuntimeError(f"Refusing unapproved action: {action}")
    if command_id <= int(state.get("last_id", 0)):
        return 0
    state["last_id"] = command_id
    state["last_action"] = action
    save_json(STATE, state)
    status = {
        "command_id": command_id,
        "action": action,
        "status": "RUNNING",
        "host": os.uname().nodename,
        "started_unix": time.time(),
    }
    publish_status(status)
    try:
        if action == "GIT_SYNC":
            git_sync()
        elif action == "SPEED_TEST":
            speed_test()
        elif action == "KIMI_PROBE":
            kimi_probe()
        elif action == "STAGE1_PREFLIGHT":
            stage1_preflight(command_id)
        elif action in {"STATUS", "IDLE"}:
            save_result(f"{action}\n")
        status.update({"status": "SUCCESS", "finished_unix": time.time()})
        publish_status(status)
        log(f"SUCCESS command={command_id} action={action}")
        return 0
    except Exception as exc:
        status.update({"status": "FAILED", "error": repr(exc), "finished_unix": time.time()})
        publish_status(status)
        log(f"FAILED command={command_id} action={action} error={exc!r}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
