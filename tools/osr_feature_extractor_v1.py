#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import ahocorasick
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from huggingface_hub import HfApi, hf_hub_url

SOURCES = [
    ("Literature-zh", "Geralt-Targaryen/Literature-zh"),
    ("ChineseWebText2.0-HighQuality", "Morton-Li/ChineseWebText2.0-HighQuality"),
]

ROW_SCHEMA = pa.schema([
    ("corpus", pa.string()), ("repo", pa.string()), ("shard", pa.string()),
    ("row", pa.int64()), ("row_sha256", pa.string()),
    ("char_len", pa.int64()), ("utf8_bytes", pa.int64()),
    ("cjk_chars", pa.int64()), ("ascii_chars", pa.int64()), ("digit_chars", pa.int64()),
    ("feature_ids", pa.list_(pa.string())), ("feature_counts", pa.list_(pa.int32())),
    ("first_positions", pa.list_(pa.int64())),
    ("regex_feature_ids", pa.list_(pa.string())), ("regex_counts", pa.list_(pa.int32())),
    ("year_min", pa.int32()), ("year_max", pa.int32()), ("explicit_year_count", pa.int32()),
])
SHARD_SCHEMA = pa.schema([
    ("corpus", pa.string()), ("repo", pa.string()), ("shard", pa.string()),
    ("shard_sha256", pa.string()), ("download_bytes", pa.int64()),
    ("rows", pa.int64()), ("rows_nonempty", pa.int64()), ("signal_rows", pa.int64()),
    ("chars", pa.int64()), ("newline_count", pa.int64()),
    ("sentence_terminal_count", pa.int64()), ("within_shard_duplicate_rows", pa.int64()),
    ("explicit_year_mentions", pa.int64()), ("year_min", pa.int32()), ("year_max", pa.int32()),
    ("scan_seconds", pa.float64()),
])
PAIR_SCHEMA = pa.schema([
    ("corpus", pa.string()), ("repo", pa.string()), ("shard", pa.string()),
    ("feature_a", pa.string()), ("feature_b", pa.string()), ("rows_cooccurring", pa.int64()),
])
FEATURE_TOTAL_SCHEMA = pa.schema([
    ("corpus", pa.string()), ("repo", pa.string()), ("shard", pa.string()),
    ("feature_id", pa.string()), ("family", pa.string()),
    ("occurrences", pa.int64()), ("rows_with_feature", pa.int64()),
])

CJK_RE = re.compile(r"[\u3400-\u9fff]")
ASCII_RE = re.compile(r"[\x00-\x7f]")
DIGIT_RE = re.compile(r"[0-9]")
YEAR_VALUE_RE = re.compile(r"(?:公元前|西元前)?([0-9]{1,4})年")


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", "utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())


def list_parquets(repo: str) -> list[str]:
    last = None
    for attempt in range(1, 6):
        try:
            return sorted(p for p in HfApi().list_repo_files(repo, repo_type="dataset") if p.endswith(".parquet"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"failed to enumerate {repo}: {last!r}")


def download(repo: str, filename: str, dest: Path) -> tuple[int, float, str]:
    url = hf_hub_url(repo, filename=filename, repo_type="dataset")
    part = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, 7):
        try:
            sha = hashlib.sha256(); total = 0; started = time.time()
            with requests.get(url, stream=True, timeout=(30, 240)) as r:
                r.raise_for_status()
                with part.open("wb") as f:
                    for block in r.iter_content(8 * 1024 * 1024):
                        if not block: continue
                        f.write(block); sha.update(block); total += len(block)
                    f.flush(); os.fsync(f.fileno())
            os.replace(part, dest)
            return total, time.time() - started, sha.hexdigest()
        except Exception as exc:  # noqa: BLE001
            last = exc
            part.unlink(missing_ok=True); dest.unlink(missing_ok=True)
            if attempt < 6:
                time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"download failed after retries: {repo}/{filename}: {last!r}")


def text_column(pf: pq.ParquetFile) -> str:
    names = [f.name for f in pf.schema_arrow if str(f.type) in {"string", "large_string"}]
    for name in ("text", "content", "body"):
        if name in names: return name
    if not names: raise RuntimeError(f"No text-like string column: {pf.schema_arrow}")
    return names[0]


def safe_name(path: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "__", path).strip("_")
    return stem[:160] + "__" + hashlib.sha1(path.encode()).hexdigest()[:10]


def build_feature_machine(schema: dict):
    term_to_features: dict[str, list[str]] = defaultdict(list)
    feature_family: dict[str, str] = {}
    for feat in schema["features"]:
        fid = feat["id"]; feature_family[fid] = feat["family"]
        for term in feat.get("terms", []):
            if fid not in term_to_features[term]: term_to_features[term].append(fid)
    machine = ahocorasick.Automaton()
    for term, fids in term_to_features.items(): machine.add_word(term, (term, tuple(fids)))
    machine.make_automaton()
    regexes = []
    for feat in schema.get("regex_features", []):
        feature_family[feat["id"]] = feat["family"]
        regexes.append((feat["id"], re.compile(feat["pattern"])))
    return machine, regexes, feature_family


def write_table(rows: list[dict], schema: pa.Schema, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema) if rows else pa.Table.from_pylist([], schema=schema)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, tmp, compression="zstd", compression_level=9, use_dictionary=True)
    os.replace(tmp, path)


def scan_shard(corpus, repo, filename, local, shard_sha256, download_bytes, machine, regexes, feature_family, part_dir):
    started = time.time(); pf = pq.ParquetFile(local); colname = text_column(pf)
    rows_nonempty=signal_rows=chars=newlines=sentence_terminals=duplicate_rows=explicit_year_mentions=0
    shard_year_min=shard_year_max=None; seen=set(); row_records=[]; pair_counts=Counter(); feature_occ=Counter(); feature_rows=Counter(); global_row=0
    for batch in pf.iter_batches(batch_size=256, columns=[colname]):
        col=batch.column(0)
        for i in range(len(col)):
            text=col[i].as_py(); row_index=global_row; global_row+=1
            if not isinstance(text,str) or not text: continue
            rows_nonempty+=1; chars+=len(text); newlines+=text.count("\n")
            sentence_terminals += sum(text.count(x) for x in ("。","！","？","!","?"))
            encoded=text.encode("utf-8"); dup=hashlib.blake2b(encoded,digest_size=8).digest()
            if dup in seen: duplicate_rows+=1
            else: seen.add(dup)
            counts=Counter(); first_pos={}
            for end,payload in machine.iter(text):
                term,fids=payload; start=end-len(term)+1
                for fid in fids:
                    counts[fid]+=1; first_pos[fid]=min(first_pos.get(fid,start),start)
            regex_counts=Counter()
            for fid,rx in regexes:
                n=sum(1 for _ in rx.finditer(text))
                if n: regex_counts[fid]=n
            years=[]
            if regex_counts.get("TEMPORAL_EXPLICIT_YEAR"):
                for m in YEAR_VALUE_RE.finditer(text):
                    v=int(m.group(1)); years.append(-v if m.group(0).startswith(("公元前","西元前")) else v)
            if years:
                explicit_year_mentions+=len(years); ymin,ymax=min(years),max(years)
                shard_year_min=ymin if shard_year_min is None else min(shard_year_min,ymin)
                shard_year_max=ymax if shard_year_max is None else max(shard_year_max,ymax)
            else: ymin=ymax=None
            if not counts and not regex_counts: continue
            signal_rows+=1; feature_ids=sorted(counts)
            for fid in feature_ids: feature_occ[fid]+=counts[fid]; feature_rows[fid]+=1
            for a,b in combinations(feature_ids,2): pair_counts[(a,b)]+=1
            row_records.append({
                "corpus":corpus,"repo":repo,"shard":filename,"row":row_index,"row_sha256":hashlib.sha256(encoded).hexdigest(),
                "char_len":len(text),"utf8_bytes":len(encoded),"cjk_chars":len(CJK_RE.findall(text)),"ascii_chars":len(ASCII_RE.findall(text)),"digit_chars":len(DIGIT_RE.findall(text)),
                "feature_ids":feature_ids,"feature_counts":[int(counts[f]) for f in feature_ids],"first_positions":[int(first_pos[f]) for f in feature_ids],
                "regex_feature_ids":sorted(regex_counts),"regex_counts":[int(regex_counts[f]) for f in sorted(regex_counts)],
                "year_min":ymin,"year_max":ymax,"explicit_year_count":len(years),
            })
    shard_record={"corpus":corpus,"repo":repo,"shard":filename,"shard_sha256":shard_sha256,"download_bytes":download_bytes,"rows":pf.metadata.num_rows,"rows_nonempty":rows_nonempty,"signal_rows":signal_rows,"chars":chars,"newline_count":newlines,"sentence_terminal_count":sentence_terminals,"within_shard_duplicate_rows":duplicate_rows,"explicit_year_mentions":explicit_year_mentions,"year_min":shard_year_min,"year_max":shard_year_max,"scan_seconds":round(time.time()-started,6)}
    pairs=[{"corpus":corpus,"repo":repo,"shard":filename,"feature_a":a,"feature_b":b,"rows_cooccurring":int(n)} for (a,b),n in sorted(pair_counts.items())]
    totals=[{"corpus":corpus,"repo":repo,"shard":filename,"feature_id":fid,"family":feature_family.get(fid,"unknown"),"occurrences":int(feature_occ[fid]),"rows_with_feature":int(feature_rows[fid])} for fid in sorted(feature_occ)]
    write_table(row_records,ROW_SCHEMA,part_dir/"row_features.parquet")
    write_table([shard_record],SHARD_SCHEMA,part_dir/"shard_features.parquet")
    write_table(pairs,PAIR_SCHEMA,part_dir/"cooccurrence.parquet")
    write_table(totals,FEATURE_TOTAL_SCHEMA,part_dir/"feature_totals.parquet")
    checkpoint={"status":"COMPLETE","corpus":corpus,"repo":repo,"shard":filename,"shard_sha256":shard_sha256,"row_feature_rows":len(row_records),"files":{"rows":"row_features.parquet","shard":"shard_features.parquet","pairs":"cooccurrence.parquet","totals":"feature_totals.parquet"}}
    atomic_json(part_dir/"checkpoint.json",checkpoint)
    return shard_record, checkpoint


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--worker-index",type=int,required=True); ap.add_argument("--worker-count",type=int,required=True); ap.add_argument("--limit-per-worker",type=int,default=0); ap.add_argument("--out-dir",required=True); ap.add_argument("--feature-schema",default="control/feature_schema_v1.json"); args=ap.parse_args()
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True); parts=out/"parts"; parts.mkdir(exist_ok=True)
    schema_bytes=Path(args.feature_schema).read_bytes(); schema=json.loads(schema_bytes.decode()); schema_sha=hashlib.sha256(schema_bytes).hexdigest(); machine,regexes,family=build_feature_machine(schema)
    inventory=[]
    for corpus,repo in SOURCES:
        for filename in list_parquets(repo): inventory.append((corpus,repo,filename))
    inventory.sort(key=lambda x:(x[0],x[2])); assigned=[x for i,x in enumerate(inventory) if i%args.worker_count==args.worker_index]
    if args.limit_per_worker>0: assigned=assigned[:args.limit_per_worker]
    successes=[]; failures=[]; bytes_downloaded=0; started=time.time()
    atomic_json(out/"assigned.json",{"worker_index":args.worker_index,"worker_count":args.worker_count,"assigned":[{"corpus":c,"repo":r,"shard":s} for c,r,s in assigned],"feature_schema_sha256":schema_sha})
    for n,(corpus,repo,filename) in enumerate(assigned,1):
        key=safe_name(f"{corpus}__{filename}"); part_dir=parts/key; part_dir.mkdir(parents=True,exist_ok=True); local=Path("/tmp")/f"osr-feature-{args.worker_index}-{n}.parquet"
        try:
            size,dl_s,shard_sha=download(repo,filename,local); bytes_downloaded+=size
            shard_record,checkpoint=scan_shard(corpus,repo,filename,local,shard_sha,size,machine,regexes,family,part_dir)
            successes.append({"corpus":corpus,"repo":repo,"shard":filename,"part":str(part_dir.relative_to(out)),"sha256":shard_sha,"signal_rows":shard_record["signal_rows"]})
            append_jsonl(out/"checkpoint.jsonl",{"status":"COMPLETE","corpus":corpus,"repo":repo,"shard":filename,"part":str(part_dir.relative_to(out)),"sha256":shard_sha})
            print(json.dumps({"progress":f"{n}/{len(assigned)}","status":"COMPLETE","shard":filename,"MiB":round(size/1048576,2),"signal_rows":shard_record["signal_rows"]},ensure_ascii=False),flush=True)
        except Exception as exc:  # noqa: BLE001
            failures.append({"corpus":corpus,"repo":repo,"shard":filename,"error":repr(exc)})
            append_jsonl(out/"failures.jsonl",{"status":"FAILED","corpus":corpus,"repo":repo,"shard":filename,"error":repr(exc)})
            print(json.dumps({"progress":f"{n}/{len(assigned)}","status":"FAILED","shard":filename,"error":repr(exc)},ensure_ascii=False),flush=True)
        finally:
            local.unlink(missing_ok=True); local.with_suffix(local.suffix+".part").unlink(missing_ok=True)
        atomic_json(out/"manifest.partial.json",{"format":"osr-feature-store-worker/v1.1","feature_schema_version":schema.get("version"),"feature_schema_sha256":schema_sha,"worker_index":args.worker_index,"worker_count":args.worker_count,"assigned_shards":len(assigned),"completed_shards":len(successes),"failed_shards":len(failures),"successes":successes,"failures":failures,"bytes_downloaded":bytes_downloaded,"elapsed_seconds":round(time.time()-started,3),"raw_text_persisted":False})
    manifest={"format":"osr-feature-store-worker/v1.1","feature_schema_version":schema.get("version"),"feature_schema_sha256":schema_sha,"worker_index":args.worker_index,"worker_count":args.worker_count,"assigned_shards":len(assigned),"completed_shards":len(successes),"failed_shards":len(failures),"successes":successes,"failures":failures,"bytes_downloaded":bytes_downloaded,"elapsed_seconds":round(time.time()-started,3),"raw_text_persisted":False,"runner":os.environ.get("RUNNER_NAME"),"github_run_id":os.environ.get("GITHUB_RUN_ID"),"github_sha":os.environ.get("GITHUB_SHA")}
    atomic_json(out/"manifest.json",manifest); print(json.dumps(manifest,ensure_ascii=False,indent=2))
    return 0 if not failures else 3

if __name__=="__main__": raise SystemExit(main())
