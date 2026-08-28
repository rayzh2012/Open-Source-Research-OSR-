#!/usr/bin/env python3
import json, os, platform, shutil, time
from pathlib import Path

out = {
    "status": "PASS",
    "time_unix": time.time(),
    "host": platform.node(),
    "platform": platform.platform(),
    "python": platform.python_version(),
    "cwd": str(Path.cwd()),
    "rclone": shutil.which("rclone"),
    "git": shutil.which("git"),
    "home": str(Path.home()),
    "repo_present": (Path.home() / "Open-Source-Research-OSR-" / ".git").is_dir(),
}
print(json.dumps(out, ensure_ascii=False, indent=2))
