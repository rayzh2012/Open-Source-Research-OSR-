#!/usr/bin/env python3
from __future__ import annotations

import base64
import configparser
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = "rayzh2012/Open-Source-Research-OSR-"
SECRET_NAME = "RCLONE_CONFIG_B64"
DEFAULT_CONFIG = Path.home() / ".config" / "rclone" / "rclone.conf"


def fail(msg: str, code: int = 2) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return code


def main() -> int:
    config_path = Path(os.environ.get("RCLONE_CONFIG", str(DEFAULT_CONFIG))).expanduser()
    if not config_path.exists():
        return fail(f"rclone config not found: {config_path}")

    raw = config_path.read_bytes()
    if not raw.strip():
        return fail("rclone config is empty")

    parser = configparser.RawConfigParser()
    try:
        parser.read_string(raw.decode("utf-8"))
    except Exception as exc:
        return fail(f"rclone config is not valid UTF-8 INI: {exc!r}")

    if "gdrive" not in parser.sections():
        return fail("rclone config has no [gdrive] remote")
    if not parser.get("gdrive", "type", fallback="").strip():
        return fail("[gdrive] remote has no type")

    gh = shutil.which("gh")
    if not gh:
        return fail("GitHub CLI 'gh' not found on PATH")

    auth = subprocess.run(
        [gh, "auth", "status"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if auth.returncode != 0:
        return fail("GitHub CLI is not authenticated; run `gh auth login` once on this Mac")

    payload = base64.b64encode(raw).decode("ascii")

    # gh secret set reads the secret body from stdin when --body is omitted.
    # Never print the payload, token, or config contents.
    p = subprocess.run(
        [gh, "secret", "set", SECRET_NAME, "--repo", REPO],
        input=payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if p.returncode != 0:
        detail = (p.stderr or p.stdout or f"exit {p.returncode}").strip()
        return fail(f"gh secret set failed: {detail}")

    print(f"OK: configured GitHub Actions secret {SECRET_NAME} for {REPO}")
    print("OK: source was local rclone config; secret value was not printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
