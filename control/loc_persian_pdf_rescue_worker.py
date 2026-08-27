#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = "gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/loc_persian_manuscripts"
EXPECTED = 173


def session() -> requests.Session:
    retry = Retry(total=10, connect=10, read=10, backoff_factor=2,
                  status_forcelist=(429,500,502,503,504),
                  allowed_methods=frozenset(["GET","HEAD"]), raise_on_status=False)
    s=requests.Session()
    s.headers.update({"Accept":"application/json,*/*;q=0.5"})
    s.mount("https://",HTTPAdapter(max_retries=retry))
    return s


def run(cmd:list[str],check:bool=True,capture:bool=False):
    print("+"," ".join(cmd),flush=True)
    return subprocess.run(cmd,check=check,text=True,capture_output=capture)


def rclone_cat(path:str)->str|None:
    p=run(["rclone","cat",path],check=False,capture=True)
    return p.stdout if p.returncode==0 else None


def rclone_copyto(src:Path,dst:str)->None:
    run(["rclone","copyto",str(src),dst,
         "--drive-chunk-size","64M","--retries","8","--low-level-retries","16",
         "--timeout","10m","--contimeout","30s","--stats","30s"])


def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def dump(path:Path,obj)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def discover_from_rescued_catalog()->list[dict]:
    p=run(["rclone","lsjson",f"{ROOT}/item_json","--files-only"],capture=True)
    entries=json.loads(p.stdout or "[]")
    rows=[]
    for x in entries:
        name=str(x.get("Name") or x.get("Path") or "")
        m=re.fullmatch(r"(\d+)\.json",Path(name).name)
        if m:
            rows.append({"item_id":m.group(1)})
    rows=sorted({r["item_id"]:r for r in rows}.values(),key=lambda r:r["item_id"])
    if len(rows)!=EXPECTED:
        raise RuntimeError(f"Rescued LOC catalog expected {EXPECTED}, got {len(rows)}")
    return rows


def get_json_with_retry(s:requests.Session,url:str,*,params:dict|None=None,attempts:int=8)->dict:
    last:Exception|None=None
    for attempt in range(1,attempts+1):
        try:
            r=s.get(url,params=params,timeout=(30,240),headers={"Accept":"application/json,*/*;q=0.5"})
            r.raise_for_status()
            obj=r.json()
            if not isinstance(obj,dict):
                raise ValueError(f"Expected JSON object, got {type(obj).__name__}")
            return obj
        except (requests.RequestException, ValueError) as exc:
            last=exc
            print(f"JSON_RETRY attempt={attempt}/{attempts} url={url} error={exc!r}",flush=True)
            if attempt<attempts:
                time.sleep(min(30,2**attempt))
    assert last is not None
    raise last


def find_resource_payload(obj:dict)->tuple[str|None,list[dict],dict|None]:
    resources=[]
    for candidate in (obj.get("resources"), (obj.get("item") or {}).get("resources")):
        if isinstance(candidate,list):
            resources.extend(x for x in candidate if isinstance(x,dict))
    seen=set(); dedup=[]
    for r in resources:
        key=json.dumps(r,sort_keys=True,ensure_ascii=False)
        if key not in seen:
            seen.add(key); dedup.append(r)
    pdf=None; chosen=None
    for r in dedup:
        if isinstance(r.get("pdf"),str) and r["pdf"].startswith("http"):
            pdf=r["pdf"]; chosen=r; break
    return pdf,dedup,chosen


def flatten_original_files(resources:list[dict])->list[dict]:
    rows=[]
    for ri,r in enumerate(resources):
        files=r.get("files")
        if not isinstance(files,list): continue
        for page_i,page in enumerate(files,1):
            entries=page if isinstance(page,list) else [page]
            originals=[]; derivatives=[]
            for f in entries:
                if not isinstance(f,dict): continue
                rec={k:f.get(k) for k in ("url","info","mimetype","size","width","height","other_name") if f.get(k) is not None}
                if f.get("mimetype") in {"image/jp2","image/tiff","image/tif"} or (isinstance(f.get("url"),str) and "storage-services" in f.get("url")):
                    originals.append(rec)
                else:
                    derivatives.append(rec)
            rows.append({"resource_index":ri,"page_index":page_i,"originals":originals,"derivatives":derivatives})
    return rows


def download(s:requests.Session,url:str,out:Path,attempts:int=8)->tuple[int,str,str]:
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix(out.suffix+".part")
    last:Exception|None=None
    for attempt in range(1,attempts+1):
        tmp.unlink(missing_ok=True)
        h=hashlib.sha256(); size=0; ctype=""
        try:
            with s.get(url,stream=True,timeout=(30,1800),headers={"Accept":"application/pdf,*/*;q=0.5"}) as r:
                r.raise_for_status(); ctype=r.headers.get("Content-Type","")
                expected=int(r.headers.get("Content-Length") or 0)
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(8*1024*1024):
                        if not chunk: continue
                        f.write(chunk); h.update(chunk); size+=len(chunk)
                if expected and size!=expected:
                    raise IOError(f"Short download: got {size}, expected {expected}")
            os.replace(tmp,out)
            return size,h.hexdigest(),ctype
        except (requests.RequestException, OSError) as exc:
            last=exc
            print(f"PDF_RETRY attempt={attempt}/{attempts} url={url} bytes={size} error={exc!r}",flush=True)
            tmp.unlink(missing_ok=True)
            if attempt<attempts:
                time.sleep(min(45,2**attempt))
    assert last is not None
    raise last


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--partition",type=int,required=True)
    ap.add_argument("--partitions",type=int,required=True)
    ap.add_argument("--work-dir",required=True)
    args=ap.parse_args()
    s=session(); rows=discover_from_rescued_catalog()
    chosen=[r for r in rows if int(hashlib.sha1(str(r["item_id"]).encode()).hexdigest(),16)%args.partitions==args.partition]
    print(f"LOC_PERSIAN_PDF partition={args.partition}/{args.partitions} selected={len(chosen)} total={len(rows)}",flush=True)
    work=Path(args.work_dir); work.mkdir(parents=True,exist_ok=True)
    result=[]; failures=[]; pdf_bytes=0; pdfs=0; cached=0; metadata_only=0

    for n,row in enumerate(chosen,1):
        iid=str(row["item_id"])
        remote=f"{ROOT}/items/{iid}"
        prior=rclone_cat(f"{remote}/COMPLETE.json")
        if prior:
            try:
                pobj=json.loads(prior)
                if pobj.get("item_id")==iid and pobj.get("status") in {"PASS","METADATA_ONLY_NO_PDF"}:
                    print(f"[{n}/{len(chosen)}] SKIP {iid}",flush=True)
                    result.append({"item_id":iid,"status":"SKIP_COMPLETE"}); cached+=1; continue
            except Exception: pass

        print(f"[{n}/{len(chosen)}] ITEM {iid}",flush=True)
        try:
            obj=get_json_with_retry(s,f"https://www.loc.gov/item/{iid}/",params={"fo":"json"})
            item_path=work/f"{iid}.item.json"; dump(item_path,obj)
            item_sha=sha256_file(item_path)
            pdf_url,resources,_=find_resource_payload(obj)
            files=flatten_original_files(resources)
            files_path=work/f"{iid}.files.json"; dump(files_path,{"item_id":iid,"resources":resources,"pages":files})
            files_sha=sha256_file(files_path)
            rclone_copyto(item_path,f"{remote}/metadata/item.json")
            rclone_copyto(files_path,f"{remote}/metadata/FILES.json")

            item_meta=obj.get("item") or {}
            complete={
                "schema_version":"osr-loc-persian-manuscript-complete-v1",
                "item_id":iid,
                "canonical_url":f"https://www.loc.gov/item/{iid}/",
                "title":item_meta.get("title") or obj.get("title"),
                "date":item_meta.get("date") or obj.get("date"),
                "language":item_meta.get("language") or obj.get("language"),
                "rights":"LOC Persian Language Manuscript Project: public domain or no known restrictions",
                "item_json_sha256":item_sha,
                "files_inventory_sha256":files_sha,
                "page_groups":len(files),
                "pdf_url":pdf_url,
            }
            if pdf_url:
                pdf_path=work/f"{iid}.pdf"
                size,pdf_sha,ctype=download(s,pdf_url,pdf_path)
                rclone_copyto(pdf_path,f"{remote}/raw/{iid}.pdf")
                complete.update({"status":"PASS","pdf_bytes":size,"pdf_sha256":pdf_sha,"pdf_content_type":ctype})
                pdf_bytes+=size; pdfs+=1
                pdf_path.unlink(missing_ok=True)
            else:
                complete.update({"status":"METADATA_ONLY_NO_PDF"})
                metadata_only+=1
            cp=work/f"{iid}.COMPLETE.json"; dump(cp,complete)
            rclone_copyto(cp,f"{remote}/COMPLETE.json")
            result.append({"item_id":iid,"status":complete["status"],"pdf_bytes":complete.get("pdf_bytes",0),"pages":len(files)})
        except Exception as exc:
            failures.append({"item_id":iid,"error":repr(exc)})
            print(f"FAILED {iid}: {exc!r}",flush=True)
        finally:
            for p in work.glob(f"{iid}.*"):
                p.unlink(missing_ok=True)
            time.sleep(0.5)

    summary={
        "schema_version":"osr-loc-persian-pdf-partition-result-v1",
        "partition":args.partition,"partitions":args.partitions,"items_selected":len(chosen),
        "pdfs_uploaded_this_run":pdfs,"pdf_bytes_uploaded_this_run":pdf_bytes,
        "cached":cached,"metadata_only_no_pdf":metadata_only,"failures":failures,
        "status":"PASS" if not failures else "PARTIAL_FAILURE","items":result,
    }
    print("RESULT_JSON="+json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return 0 if not failures else 2

if __name__=="__main__":
    raise SystemExit(main())
