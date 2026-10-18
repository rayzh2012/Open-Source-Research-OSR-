#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

# This script executes from control/, so its own directory is already on sys.path.
from loc_persian_pdf_rescue_worker import (
    ROOT, session, rclone_cat, get_json_with_retry, dump, sha256_file,
    find_resource_payload, flatten_original_files, rclone_copyto, download,
)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--item-id",required=True)
    ap.add_argument("--work-dir",required=True)
    args=ap.parse_args()
    iid=str(args.item_id)
    remote=f"{ROOT}/items/{iid}"
    prior=rclone_cat(f"{remote}/COMPLETE.json")
    if prior:
        try:
            obj=json.loads(prior)
            if obj.get("item_id")==iid and obj.get("status") in {"PASS","METADATA_ONLY_NO_PDF"}:
                print("RESULT_JSON="+json.dumps({"item_id":iid,"status":"SKIP_COMPLETE"},sort_keys=True))
                return 0
        except Exception:
            pass

    s=session()
    work=Path(args.work_dir); work.mkdir(parents=True,exist_ok=True)
    obj=get_json_with_retry(s,f"https://www.loc.gov/item/{iid}/",params={"fo":"json"},attempts=12)
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
        size,pdf_sha,ctype=download(s,pdf_url,pdf_path,attempts=12)
        rclone_copyto(pdf_path,f"{remote}/raw/{iid}.pdf")
        complete.update({"status":"PASS","pdf_bytes":size,"pdf_sha256":pdf_sha,"pdf_content_type":ctype})
    else:
        complete.update({"status":"METADATA_ONLY_NO_PDF"})

    cp=work/f"{iid}.COMPLETE.json"; dump(cp,complete)
    rclone_copyto(cp,f"{remote}/COMPLETE.json")
    print("RESULT_JSON="+json.dumps({"item_id":iid,"status":complete["status"],"pdf_bytes":complete.get("pdf_bytes",0),"page_groups":len(files)},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
