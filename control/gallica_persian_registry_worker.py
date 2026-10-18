#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SRU = "https://gallica.bnf.fr/SRU"
ROOT = "gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts"
QUERY = '((dc.language all "per") or (dc.language all "fas")) and (dc.type all "manuscrit")'


def session()->requests.Session:
    retry=Retry(total=8,connect=8,read=8,backoff_factor=1.5,
                status_forcelist=(429,500,502,503,504),
                allowed_methods=frozenset(["GET","HEAD"]),raise_on_status=False)
    s=requests.Session()
    s.headers.update({"User-Agent":"OSR-Preservation/1.0 (+https://github.com/rayzh2012/Open-Source-Research-OSR-)",
                      "Accept":"application/xml,application/json,text/plain,*/*;q=0.5"})
    s.mount("https://",HTTPAdapter(max_retries=retry))
    return s


def run(cmd:list[str]):
    print("+"," ".join(cmd),flush=True)
    subprocess.run(cmd,check=True)


def dump(path:Path,obj)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def local(tag:str)->str:
    return tag.rsplit('}',1)[-1]


def values_by_local(elem:ET.Element,name:str)->list[str]:
    out=[]
    for x in elem.iter():
        if local(x.tag)==name and x.text and x.text.strip():
            out.append(x.text.strip())
    return out


def ark_from_values(values:list[str])->str|None:
    for v in values:
        m=re.search(r'ark:/12148/([A-Za-z0-9]+)',v)
        if m:
            return m.group(1)
    return None


def classify_rights(fields:dict[str,list[str]])->dict:
    source=' | '.join(fields.get('source',[]))
    rights=' | '.join(fields.get('rights',[]))
    publisher=' | '.join(fields.get('publisher',[]))
    text=(source+' | '+rights+' | '+publisher).lower()
    partner_markers=('bibliothèque municipale','bibliotheque municipale','partner','partenaire','institut','université','universite')
    restricted_markers=('sous droits','copyright','protégé','protege','restricted','restriction')
    if any(x in text for x in restricted_markers):
        cls='REVIEW_RESTRICTED_SIGNAL'
    elif any(x in text for x in partner_markers) and 'bibliothèque nationale de france' not in text:
        cls='REVIEW_PARTNER_HOLDING'
    else:
        cls='BNF_OR_UNRESOLVED_METADATA_ONLY'
    return {"classification":cls,"source_text":source,"rights_text":rights,"publisher_text":publisher}


def get_xml(s:requests.Session,start:int,max_records:int=50)->ET.Element:
    params={"version":"1.2","operation":"searchRetrieve","query":QUERY,
            "startRecord":start,"maximumRecords":max_records,"collapsing":"false"}
    r=s.get(SRU,params=params,timeout=(30,180)); r.raise_for_status()
    return ET.fromstring(r.content)


def fetch_manifest(s:requests.Session,ark:str)->tuple[dict|None,str|None]:
    url=f"https://gallica.bnf.fr/iiif/ark:/12148/{ark}/manifest.json"
    try:
        r=s.get(url,headers={"Accept":"application/ld+json,application/json,*/*;q=0.5"},timeout=(30,180))
        if r.status_code!=200:
            return None,f"HTTP {r.status_code}"
        obj=r.json()
        if not isinstance(obj,dict):
            return None,"non-object JSON"
        return obj,None
    except Exception as exc:
        return None,repr(exc)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--work-dir',required=True)
    args=ap.parse_args()
    work=Path(args.work_dir); work.mkdir(parents=True,exist_ok=True)
    s=session()

    first=get_xml(s,1,50)
    nums=values_by_local(first,'numberOfRecords')
    total=int(nums[0]) if nums else 0
    print(f"GALLICA_PERSIAN_SRU total={total} query={QUERY}",flush=True)
    if total<=0:
        raise RuntimeError('Gallica SRU returned zero Persian manuscript records')

    records=[]; by_ark={}; raw_pages=[]
    start=1
    while start<=total:
        root=first if start==1 else get_xml(s,start,50)
        xml_bytes=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        raw_path=work/'sru'/f'{start:06d}.xml'; raw_path.parent.mkdir(parents=True,exist_ok=True); raw_path.write_bytes(xml_bytes)
        raw_pages.append(raw_path)
        page_records=[x for x in root.iter() if local(x.tag)=='record']
        before=len(by_ark)
        for rec in page_records:
            data_nodes=[x for x in rec.iter() if local(x.tag)=='recordData']
            target=data_nodes[0] if data_nodes else rec
            fields={}
            for x in target.iter():
                n=local(x.tag)
                if n in {'title','creator','contributor','subject','description','publisher','date','type','format','identifier','source','language','relation','coverage','rights'} and x.text and x.text.strip():
                    fields.setdefault(n,[]).append(x.text.strip())
            identifiers=fields.get('identifier',[])+values_by_local(rec,'recordIdentifier')
            ark=ark_from_values(identifiers)
            if not ark:
                continue
            row={"ark":ark,"fields":fields,"rights_audit":classify_rights(fields),
                 "gallica_url":f"https://gallica.bnf.fr/ark:/12148/{ark}",
                 "iiif_manifest_url":f"https://gallica.bnf.fr/iiif/ark:/12148/{ark}/manifest.json"}
            by_ark[ark]=row
        print(f"SRU_PAGE start={start} raw_records={len(page_records)} unique_delta={len(by_ark)-before} unique={len(by_ark)}",flush=True)
        start+=50
        if start<=total: time.sleep(0.25)

    manifest_ok=0; manifest_fail=[]; canvas_total=0
    manifest_rows=[]
    for i,(ark,row) in enumerate(sorted(by_ark.items()),1):
        print(f"MANIFEST {i}/{len(by_ark)} {ark}",flush=True)
        obj,err=fetch_manifest(s,ark)
        rec_path=work/'records'/f'{ark}.json'; dump(rec_path,row)
        mrow={"ark":ark,"manifest_url":row['iiif_manifest_url'],"rights_audit":row['rights_audit']}
        if obj is not None:
            mp=work/'iiif'/f'{ark}.manifest.json'; dump(mp,obj)
            manifest_ok+=1
            canvases=0
            for seq in obj.get('sequences') or []:
                if isinstance(seq,dict): canvases+=len(seq.get('canvases') or [])
            canvas_total+=canvases
            mrow.update({"status":"PASS","canvases":canvases,"manifest_sha256":hashlib.sha256(mp.read_bytes()).hexdigest()})
        else:
            manifest_fail.append({"ark":ark,"error":err})
            mrow.update({"status":"FAILED","error":err})
        manifest_rows.append(mrow)
        time.sleep(0.08)

    index_path=work/'meta'/'manifest_registry.jsonl'; index_path.parent.mkdir(parents=True,exist_ok=True)
    with index_path.open('w',encoding='utf-8') as f:
        for row in manifest_rows: f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n')
    classes={}
    for row in by_ark.values():
        c=row['rights_audit']['classification']; classes[c]=classes.get(c,0)+1
    summary={"schema_version":"osr-gallica-persian-registry-v1","query":QUERY,"sru_reported_total":total,
             "unique_arks":len(by_ark),"iiif_manifests_ok":manifest_ok,"iiif_manifests_failed":len(manifest_fail),
             "iiif_canvas_total":canvas_total,"rights_classes":classes,"manifest_failures":manifest_fail,
             "metadata_license":"Licence Ouverte / Open Licence (BnF metadata)",
             "content_policy":"Registry only. Do not bulk mirror page images until BnF-vs-partner rights classification is resolved item by item.",
             "status":"PASS" if by_ark and manifest_ok else "PARTIAL"}
    dump(work/'meta'/'SUMMARY.json',summary)

    for sub in ('sru','records','iiif','meta'):
        run(['rclone','copy',str(work/sub),f'{ROOT}/{sub}','--drive-chunk-size','64M','--transfers','6','--checkers','12','--retries','8','--low-level-retries','16','--timeout','10m','--contimeout','30s'])
    print('RESULT_JSON='+json.dumps(summary,ensure_ascii=False,sort_keys=True))
    return 0 if summary['status'] in {'PASS','PARTIAL'} else 2

if __name__=='__main__':
    raise SystemExit(main())
