#!/usr/bin/env python3
"""OSR Stage-2 minimal preflight gate.

Validates the Stage-1 v3 identity root and a 5-schema real-data canary before
allowing the 1,788-shard Stage-2 Direct Miner to run. Works in Colab or macOS.
"""
from __future__ import annotations

import hashlib, json, os, re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import pyarrow.parquet as pq
except Exception as exc:
    raise SystemExit("pyarrow is required") from exc

DRIVE = Path(os.environ.get("OSR_DRIVE_ROOT", "/content/drive/MyDrive"))
WORKSPACE = Path(os.environ.get("OSR_WORKSPACE", str(DRIVE / "OSR_WORK_SPACE")))
EXPECTED_SHARDS = 1788
EXPECTED_SOURCE_COUNTS = {"Literature-zh": 233, "ChineseWebText2.0": 1555}
REQUIRED_IDENTITY_FIELDS = ("size_bytes", "mtime_ns", "rows", "row_groups", "schema_sha256")
MANIFEST_CANDIDATES = [
    WORKSPACE / "Stage1_Identity_v3" / "manifest_canonical_v3.jsonl",
    WORKSPACE / "Stage1_Outputs_v3" / "manifest_canonical_v3.jsonl",
    WORKSPACE / "manifest_canonical_v3.jsonl",
]
VERIFY_CANDIDATES = [
    WORKSPACE / "Stage1_Identity_v3" / "STAGE1_V3_VERIFIED.json",
    WORKSPACE / "Stage1_Outputs_v3" / "STAGE1_V3_VERIFIED.json",
    WORKSPACE / "STAGE1_V3_VERIFIED.json",
]
PREFLIGHT_DIR = WORKSPACE / "Stage2_Preflight_v1"
SENTINEL = PREFLIGHT_DIR / "STAGE2_PREFLIGHT_VERIFIED.json"


def sha256_bytes(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

def first_present(d: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in d and d[name] not in (None, ""): return d[name]
    return None

def discover_one(candidates: list[Path], filename: str) -> Path:
    for p in candidates:
        if p.exists(): return p
    hits = list(WORKSPACE.rglob(filename))
    if len(hits) != 1: raise AssertionError(f"expected exactly one {filename}, found {len(hits)}")
    return hits[0]

def load_jsonl(path: Path):
    raw = path.read_bytes(); rows=[]
    for line in raw.splitlines():
        if line.strip(): rows.append(json.loads(line))
    return raw, rows

def resolve_source(e):
    s=str(first_present(e,"source","dataset","corpus") or ""); sl=s.lower()
    if "literature" in sl: return "Literature-zh"
    if "webtext" in sl or "chinesewebtext" in sl: return "ChineseWebText2.0"
    return s

def resolve_path(e):
    raw=first_present(e,"path","file_path","filepath","canonical_path")
    if raw:
        p=Path(str(raw))
        if p.exists(): return p
        text=str(raw)
        for prefix in ("/content/drive/MyDrive/","MyDrive/","/MyDrive/"):
            if text.startswith(prefix):
                q=DRIVE/text[len(prefix):]
                if q.exists(): return q
    rel=first_present(e,"relative_path")
    if rel:
        source=resolve_source(e)
        roots={
            "Literature-zh": DRIVE/"Literature-zh_229GB",
            "ChineseWebText2.0": DRIVE/"ChineseWebText2.0-HighQuality_279GB",
        }
        q=roots[source]/str(rel)
        if q.exists(): return q
    filename=first_present(e,"filename","name")
    hits=list(DRIVE.rglob(str(filename))) if filename else []
    if len(hits)!=1: raise AssertionError(f"cannot uniquely resolve {filename}: {len(hits)} hits")
    return hits[0]
def schema_sha(e):
    v=first_present(e,"schema_sha256","schema_sha","schema_hash")
    if not v: raise AssertionError("missing schema_sha256")
    return str(v)
def edge_fingerprint(path, edge_bytes=1024*1024):
    size=path.stat().st_size
    with path.open("rb") as f:
        first=f.read(min(edge_bytes,size)); f.seek(max(0,size-edge_bytes)); last=f.read(min(edge_bytes,size))
    return sha256_bytes(first),sha256_bytes(last)
def validate_identity(e,path):
    st=path.stat(); pf=pq.ParquetFile(path); md=pf.metadata
    assert st.st_size==int(first_present(e,"size_bytes","bytes","file_size"))
    # mtime is retained in the manifest, but Google Drive for Desktop can present a
    # different local nanosecond representation than Colab/Drive FUSE. Size + edges +
    # footer/schema are the portable data identity; mtime mismatch is reported, not fatal.
    manifest_mtime=int(first_present(e,"mtime_ns","modified_ns","stat_mtime_ns"))
    assert md.num_rows==int(first_present(e,"rows","row_count","num_rows"))
    assert md.num_row_groups==int(first_present(e,"row_groups","row_group_count","num_row_groups"))
    expected=schema_sha(e)
    candidates={sha256_bytes(str(pf.schema_arrow).encode()),sha256_bytes(pf.schema_arrow.serialize().to_pybytes())}
    assert expected in candidates, (path.name,expected,candidates)
    exp_first=first_present(e,"first_edge_sha256","edge_first_sha256","first_sha256")
    exp_last=first_present(e,"last_edge_sha256","edge_last_sha256","last_sha256")
    if exp_first and exp_last:
        got_first,got_last=edge_fingerprint(path); assert got_first==str(exp_first); assert got_last==str(exp_last)
    return {"path":str(path),"mtime_match":st.st_mtime_ns==manifest_mtime}
def text_canary(path):
    pf=pq.ParquetFile(path); assert "text" in pf.schema_arrow.names
    vals=pf.read_row_group(0,columns=["text"]).column("text").to_pylist()
    idx=next(i for i,x in enumerate(vals) if isinstance(x,str) and x.strip())
    text=vals[idx]; raw_sha=sha256_bytes(text.encode()); cjk=re.findall(r"[\u3400-\u9fff]",text)
    token="".join(cjk[:4]) if len(cjk)>=2 else text.strip()[:8]; assert token in text
    reread=pf.read_row_group(0,columns=["text"]).column("text")[idx].as_py(); assert sha256_bytes(reread.encode())==raw_sha
    return {"row_group":0,"row_index_within_group":idx,"token":token,"raw_text_sha256":raw_sha,"round_trip_ok":True}

def main():
    manifest=discover_one(MANIFEST_CANDIDATES,"manifest_canonical_v3.jsonl")
    verify_path=discover_one(VERIFY_CANDIDATES,"STAGE1_V3_VERIFIED.json")
    verify=json.loads(verify_path.read_text("utf-8")); assert bool(first_present(verify,"verified","stage1_v3_verified")) is True
    raw,entries=load_jsonl(manifest); digest=sha256_bytes(raw); declared=first_present(verify,"manifest_sha256","canonical_manifest_sha256","manifest_digest")
    assert digest==str(declared); assert len(entries)==EXPECTED_SHARDS
    sources=Counter(resolve_source(e) for e in entries); assert sources==Counter(EXPECTED_SOURCE_COUNTS),sources
    for e in entries:
        missing=[k for k in REQUIRED_IDENTITY_FIELDS if first_present(e,k) is None]; assert not missing,missing
    by_source=defaultdict(list)
    for e in entries: by_source[resolve_source(e)].append(e)
    expected_ranges={"Literature-zh":set(range(1,234)),"ChineseWebText2.0":set(range(0,1555))}
    for source,group in by_source.items():
        ords=[int(first_present(e,"ordinal","shard_ordinal","index")) for e in group if first_present(e,"ordinal","shard_ordinal","index") is not None]
        if ords: assert set(ords)==expected_ranges[source]
    schemas=defaultdict(list)
    for e in entries: schemas[schema_sha(e)].append(e)
    assert len(schemas)==5,len(schemas)
    reps=[]
    for s,group in sorted(schemas.items()):
        e=sorted(group,key=lambda x:str(first_present(x,"filename","name","canonical_path")))[0]; p=resolve_path(e)
        reps.append({"source":resolve_source(e),"schema_sha256":s,"identity":validate_identity(e,p),"canary":text_canary(p)})
    result={"verified":True,"gate":"STAGE2_MINIMAL_PREFLIGHT_V1","manifest_sha256":digest,"canonical_shards":len(entries),"source_counts":dict(sources),"schema_variants":5,"representatives":reps}
    PREFLIGHT_DIR.mkdir(parents=True,exist_ok=True); tmp=SENTINEL.with_suffix(".tmp"); tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n"); os.replace(tmp,SENTINEL)
    readback=json.loads(SENTINEL.read_text()); assert readback["verified"] and readback["manifest_sha256"]==digest
    print("✅ STAGE-2 MINIMAL PREFLIGHT PASS"); print("manifest_sha256:",digest); print("sentinel:",SENTINEL)
if __name__=="__main__": main()
