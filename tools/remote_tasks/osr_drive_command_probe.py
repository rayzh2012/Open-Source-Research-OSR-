#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

RCLONE = shutil.which("rclone") or "/usr/local/bin/rclone"
REMOTE_DIR = "gdrive:OSR_WORK_SPACE/RemoteControl"
DOC_NAME = "OSR_CONTROL_COMMAND.txt"
DOC_ID = "1_cLvbcVFycfapPSWCTkhTgva4IE-lqAwnmm92yhTn3w"


def run(cmd):
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
    return {
        "cmd": cmd,
        "returncode": p.returncode,
        "stdout": (p.stdout or "")[:12000],
        "stderr": (p.stderr or "")[:12000],
    }


def main():
    tests = []
    tests.append(run([RCLONE, "--drive-export-formats", "txt", "lsf", REMOTE_DIR]))
    tests.append(run([
        RCLONE, "--drive-export-formats", "txt",
        "--include", DOC_NAME,
        "cat", REMOTE_DIR,
    ]))
    tests.append(run([
        RCLONE, "--drive-export-formats", "txt",
        "cat", REMOTE_DIR + "/" + DOC_NAME,
    ]))
    with tempfile.TemporaryDirectory(prefix="osr-drive-probe-") as td:
        out = str(Path(td) / "command.txt")
        tests.append(run([
            RCLONE, "--drive-export-formats", "txt",
            "backend", "copyid", "gdrive:", DOC_ID, out,
        ]))
        if Path(out).exists():
            try:
                copied = Path(out).read_text("utf-8")
            except Exception as exc:
                copied = f"<read failed: {exc!r}>"
        else:
            copied = "<missing>"
    print(json.dumps({
        "status": "PASS",
        "rclone": RCLONE,
        "remote_dir": REMOTE_DIR,
        "tests": tests,
        "copyid_file_content": copied[:12000],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
