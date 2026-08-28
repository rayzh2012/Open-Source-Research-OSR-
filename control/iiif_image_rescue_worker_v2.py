#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess

import iiif_image_rescue_worker as base


def remote_manifests(source_id: str) -> list[str]:
    path = f"{base.ROOT}/{source_id}/iiif"
    p = subprocess.run(["rclone", "lsjson", path, "--files-only", "--recursive"], text=True, capture_output=True)
    if p.returncode != 0:
        # Upstream manifest discovery has not completed yet. This is a readiness state, not an image failure.
        print(f"MANIFESTS_NOT_READY source={source_id} path={path} rc={p.returncode} stderr={p.stderr.strip()}", flush=True)
        return []
    rows = json.loads(p.stdout or "[]")
    return sorted(x["Path"] for x in rows if x.get("Path", "").lower().endswith(".json"))


base.remote_manifests = remote_manifests

if __name__ == "__main__":
    raise SystemExit(base.main())
