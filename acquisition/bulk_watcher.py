#!/usr/bin/env python3
import json, os, sys, time, hashlib, subprocess, pathlib, random
from datetime import datetime, timezone

try:
    import requests
    from huggingface_hub import HfApi, hf_hub_url
except Exception:
    print("Missing deps. Run installer first.", file=sys.stderr)
    raise

REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
CFG = REPO_DIR / "acquisition" / "targets.json"
APP = pathlib.Path.home() / "Library" / "Application Support" / "OSR Acquisition"
CACHE = APP / "cache"
STATE = APP / "state.json"
PLAN = APP / "plans"
LOG = APP / "logs"
for p in (APP, CACHE, PLAN, LOG): p.mkdir(parents=True, exist_ok=True)

HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
api = HfApi(token=HF_TOKEN or None)
http = requests.Session()
if HF_TOKEN:
    http.headers.update({"Authorization": f"Bearer {HF_TOKEN}"})
http.headers.update({"User-Agent": "osr-bulk-watcher/1.0"})


def now(): return datetime.now(timezone.utc).isoformat()

def load_json(path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default

def save_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)

def run(cmd, check=True, capture=True):
    p = subprocess.run(cmd, text=True, capture_output=capture)
    if check and p.returncode:
        raise RuntimeError(f"command failed {p.returncode}: {' '.join(cmd)}\n{p.stderr[-2000:]}")
    return p

def remote_stat(remote_path):
    p = run(["rclone", "size", "--json", remote_path], check=False)
    if p.returncode:
        return None
    try:
        j = json.loads(p.stdout)
        if int(j.get("count", 0)) == 1:
            return int(j.get("bytes", -1))
    except Exception:
        pass
    return None

def upload(local_path, remote_path):
    run([
        "rclone", "copyto", str(local_path), remote_path,
        "--drive-chunk-size", "256M", "--transfers", "1", "--checkers", "4",
        "--retries", "100", "--low-level-retries", "100", "--retries-sleep", "30s",
        "--stats", "30s", "--stats-one-line"
    ], capture=False)
    size = remote_stat(remote_path)
    if size != local_path.stat().st_size:
        raise RuntimeError(f"remote size mismatch: local={local_path.stat().st_size} remote={size}")

def plan_path(repo_id):
    return PLAN / (repo_id.replace("/", "__") + ".json")

def enumerate_repo(repo_id, repo_type, exts):
    pp = plan_path(repo_id)
    cached = load_json(pp, None)
    if cached and cached.get("files"):
        return cached["files"]
    for attempt in range(10):
        try:
            out = []
            for item in api.list_repo_tree(repo_id=repo_id, repo_type=repo_type, recursive=True, expand=True):
                path = getattr(item, "path", "")
                size = getattr(item, "size", None)
                if not path or not isinstance(size, int) or size <= 0:
                    continue
                if exts and not path.lower().endswith(tuple(x.lower() for x in exts)):
                    continue
                lfs = getattr(item, "lfs", None)
                sha256 = getattr(lfs, "sha256", None) if lfs else None
                out.append({"path": path, "size": size, "sha256": sha256})
            out.sort(key=lambda x: x["path"])
            save_json(pp, {"repo_id": repo_id, "generated": now(), "files": out})
            return out
        except Exception as e:
            wait = min(900, 60 * (2 ** attempt)) + random.randint(0, 20)
            print("enumeration retry", attempt + 1, repr(e), "sleep", wait)
            time.sleep(wait)
    raise RuntimeError(f"cannot enumerate {repo_id}")

def download(repo_id, repo_type, meta, local):
    expected = int(meta["size"])
    part = local.with_suffix(local.suffix + ".part")
    got = part.stat().st_size if part.exists() else 0
    url = hf_hub_url(repo_id=repo_id, filename=meta["path"], repo_type=repo_type)
    for attempt in range(30):
        headers = {"Range": f"bytes={got}-"} if got else {}
        try:
            r = http.get(url, headers=headers, stream=True, allow_redirects=True, timeout=600)
            if r.status_code == 429:
                wait = int(float(r.headers.get("Retry-After", 120))) + random.randint(0, 15)
                print("HF 429; sleep", wait)
                time.sleep(wait); continue
            if r.status_code not in (200, 206):
                raise RuntimeError(f"HF HTTP {r.status_code}: {r.text[:300]}")
            if got and r.status_code == 200:
                got = 0
                part.unlink(missing_ok=True)
            mode = "ab" if got and r.status_code == 206 else "wb"
            with part.open(mode) as f:
                for chunk in r.iter_content(16 * 1024 * 1024):
                    if chunk:
                        f.write(chunk); got += len(chunk)
            if got == expected:
                part.replace(local)
                return
            raise RuntimeError(f"incomplete {got}/{expected}")
        except Exception as e:
            wait = min(900, 30 * (2 ** min(attempt, 5))) + random.randint(0, 20)
            print("download retry", attempt + 1, repr(e), "sleep", wait)
            time.sleep(wait)
            got = part.stat().st_size if part.exists() else 0
    raise RuntimeError(f"download retries exhausted: {repo_id}:{meta['path']}")

def publish_status(cfg, state):
    status = APP / "bulk_watcher_status.json"
    payload = {
        "updated": now(),
        "host": os.uname().nodename,
        "completed_files": len(state.get("completed", {})),
        "last": state.get("last"),
        "errors": state.get("errors", [])[-20:],
    }
    save_json(status, payload)
    remote = f"{cfg['drive_remote']}:{cfg['drive_root'].rstrip('/')}/{cfg['status_drive_path'].lstrip('/')}"
    try: upload(status, remote)
    except Exception as e: print("status upload failed", repr(e))

def main():
    cfg = load_json(CFG, None)
    if not cfg: raise RuntimeError("targets.json missing/invalid")
    state = load_json(STATE, {"completed": {}, "errors": []})
    targets = sorted([t for t in cfg["targets"] if t.get("enabled", True)], key=lambda t: t.get("priority", 100))

    for t in targets:
        files = enumerate_repo(t["repo_id"], t.get("repo_type", "dataset"), t.get("extensions", []))
        for meta in files:
            key = f"{t['repo_id']}::{meta['path']}"
            if key in state["completed"]:
                continue
            remote = f"{cfg['drive_remote']}:{cfg['drive_root'].rstrip('/')}/{t['destination'].strip('/')}/{meta['path']}"
            rsize = remote_stat(remote)
            if rsize == int(meta["size"]):
                state["completed"][key] = {"size": rsize, "remote": remote, "completed": now(), "method": "remote-size-skip"}
                state["last"] = {"status": "skip-existing", "key": key, "time": now()}
                save_json(STATE, state); publish_status(cfg, state)
                return 0

            safe = hashlib.sha1(key.encode()).hexdigest() + pathlib.Path(meta["path"]).suffix
            local = CACHE / safe
            try:
                print("DOWNLOAD", key, meta["size"])
                download(t["repo_id"], t.get("repo_type", "dataset"), meta, local)
                print("UPLOAD", remote)
                upload(local, remote)
                state["completed"][key] = {"size": meta["size"], "sha256": meta.get("sha256"), "remote": remote, "completed": now()}
                state["last"] = {"status": "uploaded", "key": key, "time": now()}
                local.unlink(missing_ok=True)
                local.with_suffix(local.suffix + ".part").unlink(missing_ok=True)
                save_json(STATE, state); publish_status(cfg, state)
                return 0
            except Exception as e:
                err = {"time": now(), "key": key, "error": repr(e)}
                state["errors"].append(err); state["last"] = {"status": "error", **err}
                save_json(STATE, state); publish_status(cfg, state)
                print("ERROR", err, file=sys.stderr)
                return 2

    state["last"] = {"status": "idle-all-complete", "time": now()}
    save_json(STATE, state); publish_status(cfg, state)
    time.sleep(int(cfg.get("idle_sleep_seconds", 600)))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
