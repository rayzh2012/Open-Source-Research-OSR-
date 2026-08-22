#!/usr/bin/env python3
from __future__ import annotations

import glob
import json
import os
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
ALLOWED = {"IDLE", "STATUS", "STAGE1_PREFLIGHT"}
REMOTE_STATUS = "gdrive:OSR_WORK_SPACE/RemoteControl/OSR_CONTROL_STATUS.json"


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
    req = urllib.request.Request(url, headers={"User-Agent": "osr-command-watcher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url: str, path: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "osr-command-watcher/1.0"})
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
        if p.is_dir():
            return p

    mount = Path.home() / "OSR-GDrive"
    mount.mkdir(exist_ok=True)
    if shutil_which("rclone"):
        # If already mounted, use it. Otherwise try a daemon mount; this may require macFUSE.
        probe = run(["rclone", "lsd", "gdrive:"], capture_output=True)
        if probe.returncode == 0:
            m = run([
                "rclone", "mount", "gdrive:", str(mount),
                "--vfs-cache-mode", "minimal", "--daemon"
            ], capture_output=True)
            if m.returncode == 0:
                for _ in range(20):
                    if mount.is_dir() and any(mount.iterdir()):
                        return mount
                    time.sleep(1)
    raise RuntimeError(
        "No local Google Drive filesystem found. Install/enable Google Drive for Desktop, "
        "or make rclone mount work and set OSR_DRIVE_ROOT."
    )


def shutil_which(name: str):
    import shutil
    return shutil.which(name)


def publish_status(obj: dict) -> None:
    save_json(STATUS, obj)
    if shutil_which("rclone"):
        run(["rclone", "copyto", str(STATUS), REMOTE_STATUS], capture_output=True)


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

    p1 = run([
        sys.executable, str(stage1),
        "--drive-root", str(drive),
        "--out-dir", str(out_dir),
    ], env=env)
    if p1.returncode != 0:
        raise RuntimeError(f"Stage-1 v3 failed with exit {p1.returncode}")

    p2 = run([sys.executable, str(preflight)], env=env)
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

    # Claim before execution so a crash never repeats the same command implicitly.
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
        if action == "STAGE1_PREFLIGHT":
            stage1_preflight(command_id)
        elif action in {"STATUS", "IDLE"}:
            pass
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
