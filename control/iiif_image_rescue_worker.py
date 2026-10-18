#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = "gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE"


def session() -> requests.Session:
    retry = Retry(total=8, connect=8, read=8, backoff_factor=1.5,
                  status_forcelist=(429,500,502,503,504),
                  allowed_methods=frozenset(["GET","HEAD"]), raise_on_status=False)
    s=requests.Session()
    s.headers["User-Agent"]="OSR-IIIF-Rescue/1.0 (digital preservation research)"
    s.mount("https://",HTTPAdapter(max_retries=retry))
    return s


def run(cmd:list[str], check:bool=True, capture:bool=False):
    print("+"," ".join(cmd),flush=True)
    return subprocess.run(cmd,check=check,text=True,capture_output=capture)


def rclone_cat(path:str)->str|None:
    p=run(["rclone","cat",path],check=False,capture=True)
    return p.stdout if p.returncode==0 else None


def rclone_copyto(src:Path,dst:str)->None:
    run(["rclone","copyto",str(src),dst,"--drive-chunk-size","64M","--retries","8","--low-level-retries","16","--timeout","10m","--contimeout","30s"])


def remote_manifests(source_id:str)->list[str]:
    p=run(["rclone","lsjson",f"{ROOT}/{source_id}/iiif","--files-only","--recursive"],capture=True)
    rows=json.loads(p.stdout or "[]")
    return sorted(x["Path"] for x in rows if x.get("Path","").lower().endswith(".json"))


def sha256_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def dump(path:Path,obj)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def collect_text(obj)->str:
    vals=[]
    def walk(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if str(k).lower() in {"rights","license","attribution","value","label"}:
                    vals.append(str(v))
                walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
        elif isinstance(x,str): vals.append(x)
    walk(obj)
    return "\n".join(vals).lower()


def rights_allowed(manifest:dict,policy:str)->tuple[bool,str]:
    if policy=="collection_clear":
        return True,"collection-level rights cleared"
    text=collect_text(manifest)
    allow=[
        "public domain",
        "creativecommons.org/publicdomain",
        "creativecommons.org/public-domain",
        "open government licence",
        "open-government-licence",
        "nationalarchives.gov.uk/doc/open-government-licence",
    ]
    for token in allow:
        if token in text:
            return True,token
    return False,"no explicit allowlisted rights statement in manifest"


def service_id(service)->str|None:
    if isinstance(service,dict):
        return service.get("id") or service.get("@id")
    if isinstance(service,list):
        for x in service:
            u=service_id(x)
            if u: return u
    return None


def body_image_url(body)->str|None:
    if isinstance(body,list):
        for b in body:
            u=body_image_url(b)
            if u: return u
        return None
    if not isinstance(body,dict): return None
    sid=service_id(body.get("service"))
    if sid:
        return sid.rstrip("/")+"/full/full/0/default.jpg"
    return body.get("id") or body.get("@id")


def image_urls(m:dict)->list[dict]:
    out=[]
    # IIIF Presentation 2.x
    for seq in m.get("sequences",[]) or []:
        for canvas in seq.get("canvases",[]) or []:
            label=canvas.get("label")
            for ann in canvas.get("images",[]) or []:
                u=body_image_url(ann.get("resource"))
                if u: out.append({"url":u,"label":label})
    # IIIF Presentation 3.x
    for canvas in m.get("items",[]) or []:
        label=canvas.get("label")
        for page in canvas.get("items",[]) or []:
            for ann in page.get("items",[]) or []:
                u=body_image_url(ann.get("body"))
                if u: out.append({"url":u,"label":label})
    seen=set(); dedup=[]
    for x in out:
        if x["url"] not in seen:
            seen.add(x["url"]); dedup.append(x)
    return dedup


def download(s:requests.Session,url:str,path:Path)->tuple[int,str,str]:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".part")
    tmp.unlink(missing_ok=True)
    h=hashlib.sha256(); size=0; ctype=""
    with s.get(url,stream=True,timeout=(30,900)) as r:
        r.raise_for_status(); ctype=r.headers.get("Content-Type","")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(4*1024*1024):
                if not chunk: continue
                f.write(chunk); h.update(chunk); size+=len(chunk)
    os.replace(tmp,path)
    return size,h.hexdigest(),ctype


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-id",required=True)
    ap.add_argument("--partition",type=int,required=True)
    ap.add_argument("--partitions",type=int,required=True)
    ap.add_argument("--rights-policy",choices=["collection_clear","manifest_allowlist"],required=True)
    ap.add_argument("--work-dir",required=True)
    args=ap.parse_args()
    all_paths=remote_manifests(args.source_id)
    chosen=[p for p in all_paths if int(hashlib.sha1(p.encode()).hexdigest(),16)%args.partitions==args.partition]
    print(f"SOURCE={args.source_id} manifests={len(all_paths)} partition={args.partition}/{args.partitions} chosen={len(chosen)}")
    s=session(); work=Path(args.work_dir); work.mkdir(parents=True,exist_ok=True)
    rows=[]; failures=[]; complete_count=0; skipped_rights=0; images_total=0; bytes_total=0
    for n,rel in enumerate(chosen,1):
        stem=Path(rel).stem
        manifest_local=work/f"manifest-{stem}.json"
        run(["rclone","copyto",f"{ROOT}/{args.source_id}/iiif/{rel}",str(manifest_local)])
        m=json.loads(manifest_local.read_text(encoding="utf-8"))
        msha=sha256_file(manifest_local)
        dest=f"{ROOT}/{args.source_id}/images/{stem}"
        prior=rclone_cat(f"{dest}/COMPLETE.json")
        if prior:
            try:
                if json.loads(prior).get("manifest_sha256")==msha:
                    rows.append({"manifest":rel,"status":"SKIP_COMPLETE","manifest_sha256":msha})
                    complete_count+=1
                    continue
            except Exception: pass
        allowed,reason=rights_allowed(m,args.rights_policy)
        if not allowed:
            rows.append({"manifest":rel,"status":"SKIP_RIGHTS","manifest_sha256":msha,"reason":reason})
            skipped_rights+=1
            continue
        imgs=image_urls(m)
        if not imgs:
            failures.append({"manifest":rel,"error":"NO_IMAGE_URLS","manifest_sha256":msha})
            continue
        ledger=[]; ok=True
        for i,x in enumerate(imgs,1):
            url=x["url"]
            p=work/f"page-{stem}-{i:05d}.jpg"
            try:
                size,sha,ctype=download(s,url,p)
                remote_page=f"{dest}/pages/{i:05d}.jpg"
                rclone_copyto(p,remote_page)
                ledger.append({"index":i,"source_url":url,"bytes":size,"sha256":sha,"content_type":ctype,"label":x.get("label")})
                images_total+=1; bytes_total+=size
            except Exception as e:
                failures.append({"manifest":rel,"page":i,"url":url,"error":repr(e)})
                ok=False; break
            finally:
                p.unlink(missing_ok=True)
        if not ok: continue
        complete={
            "schema_version":"osr-iiif-image-rescue-complete-v1",
            "source_id":args.source_id,"manifest_path":rel,"manifest_sha256":msha,
            "rights_policy":args.rights_policy,"rights_reason":reason,
            "pages":len(ledger),"bytes":sum(x["bytes"] for x in ledger),"files":ledger,
        }
        cp=work/f"complete-{stem}.json"; dump(cp,complete)
        # COMPLETE is written last and is the durable manuscript-level checkpoint.
        rclone_copyto(cp,f"{dest}/COMPLETE.json")
        complete_count+=1
        rows.append({"manifest":rel,"status":"PASS","manifest_sha256":msha,"pages":len(ledger),"bytes":complete["bytes"]})
    result={
        "source_id":args.source_id,"partition":args.partition,"partitions":args.partitions,
        "manifests_total":len(all_paths),"manifests_selected":len(chosen),
        "manuscripts_complete_or_cached":complete_count,"skipped_rights":skipped_rights,
        "images_uploaded_this_run":images_total,"bytes_uploaded_this_run":bytes_total,
        "failures":failures,"status":"PASS" if not failures else "PARTIAL_FAILURE","rows":rows,
        "elapsed_seconds":round(time.time()-os.path.getmtime(manifest_local),3) if chosen and manifest_local.exists() else None,
    }
    print("RESULT_JSON="+json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if not failures else 2

if __name__=="__main__":
    raise SystemExit(main())
