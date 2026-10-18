#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import subprocess
from pathlib import Path

ROOT = "gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/loc_persian_manuscripts"
EXPECTED = 173


def run(cmd:list[str],check:bool=True,capture:bool=False):
    return subprocess.run(cmd,check=check,text=True,capture_output=capture)


def list_catalog_ids()->list[str]:
    p=run(["rclone","lsjson",f"{ROOT}/item_json","--files-only"],capture=True)
    entries=json.loads(p.stdout or "[]")
    ids=[]
    for x in entries:
        name=str(x.get("Name") or x.get("Path") or "")
        m=re.fullmatch(r"(\d+)\.json",Path(name).name)
        if m: ids.append(m.group(1))
    return sorted(set(ids))


def read_complete(iid:str)->tuple[str,dict|None,str|None]:
    p=run(["rclone","cat",f"{ROOT}/items/{iid}/COMPLETE.json"],check=False,capture=True)
    if p.returncode!=0 or not p.stdout.strip():
        return iid,None,(p.stderr or "missing").strip()[-500:]
    try:
        obj=json.loads(p.stdout)
        return iid,obj,None
    except Exception as exc:
        return iid,None,repr(exc)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="loc_persian_rescue_status.json")
    ap.add_argument("--workers",type=int,default=20)
    args=ap.parse_args()

    ids=list_catalog_ids()
    if len(ids)!=EXPECTED:
        raise SystemExit(f"catalog mismatch: expected {EXPECTED}, got {len(ids)}")

    complete:dict[str,dict]={}
    missing=[]
    errors=[]
    with ThreadPoolExecutor(max_workers=max(1,args.workers)) as ex:
        futs={ex.submit(read_complete,iid):iid for iid in ids}
        for fut in as_completed(futs):
            iid,obj,err=fut.result()
            if obj is None:
                missing.append(iid)
                if err and "directory not found" not in err.lower() and "object not found" not in err.lower():
                    errors.append({"item_id":iid,"error":err})
            else:
                complete[iid]=obj

    pass_ids=[]; metadata_only=[]; other=[]
    pdf_bytes=0; page_groups=0
    for iid,obj in sorted(complete.items()):
        status=obj.get("status")
        if status=="PASS":
            pass_ids.append(iid)
            pdf_bytes+=int(obj.get("pdf_bytes") or 0)
            page_groups+=int(obj.get("page_groups") or 0)
        elif status=="METADATA_ONLY_NO_PDF":
            metadata_only.append(iid)
            page_groups+=int(obj.get("page_groups") or 0)
        else:
            other.append({"item_id":iid,"status":status})

    out={
        "schema_version":"osr-loc-persian-rescue-audit-v1",
        "expected_items":EXPECTED,
        "catalog_items":len(ids),
        "checkpoints_present":len(complete),
        "pdf_complete":len(pass_ids),
        "metadata_only_no_pdf":len(metadata_only),
        "missing_checkpoints":len(missing),
        "pdf_bytes":pdf_bytes,
        "pdf_gib":round(pdf_bytes/(1024**3),3),
        "page_groups":page_groups,
        "pass_item_ids":pass_ids,
        "metadata_only_item_ids":metadata_only,
        "missing_item_ids":sorted(missing),
        "other_statuses":other,
        "read_errors":errors,
        "status":"PASS" if len(pass_ids)+len(metadata_only)==EXPECTED and not other else "INCOMPLETE",
    }
    Path(args.out).write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("RESULT_JSON="+json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
