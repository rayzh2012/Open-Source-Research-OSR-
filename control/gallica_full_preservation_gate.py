#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess

SMOKE_AUDIT='gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts/_audit/GALlica_IIIF_FULL_SMOKE_AUDIT.json'
CENSUS='gdrive:龍族古籍源庫｜Dragon Source Corpus/ISLAMIC_PERSIAN_RESCUE/gallica_persian_manuscripts/census/pagecount_v1/PAGECOUNT_CENSUS_COMPLETE.json'


def rclone_json(path:str):
    p=subprocess.run(['rclone','cat',path],text=True,capture_output=True)
    if p.returncode:
        return None
    try:return json.loads(p.stdout)
    except Exception:return None


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--request',required=True); a=ap.parse_args()
    req=json.load(open(a.request,encoding='utf-8'))
    smoke=rclone_json(SMOKE_AUDIT); census=rclone_json(CENSUS)
    checks={
        'request_enabled': bool(req.get('enabled')),
        'smoke_audit_pass': bool(smoke and smoke.get('status')=='PASS' and int(smoke.get('total_pages') or 0)==144 and int(smoke.get('total_image_bytes') or 0)>0 and int(smoke.get('total_readback_bytes') or -1)==int(smoke.get('total_image_bytes') or -2)),
        'census_pass': bool(census and census.get('status')=='PASS' and int(census.get('rows') or 0)==1472 and int(census.get('unique_arks') or 0)==1472 and int(census.get('failed') or 0)==0),
        'request_expected_arks': int(req.get('expected_arks') or 0)==1472,
    }
    out={
        'schema_version':'osr-gallica-full-preservation-gate-v1',
        'status':'READY' if all(checks.values()) else 'BLOCKED',
        'checks':checks,
        'smoke_summary':None if not smoke else {'status':smoke.get('status'),'pages':smoke.get('total_pages'),'bytes':smoke.get('total_image_bytes')},
        'census_summary':None if not census else {'status':census.get('status'),'rows':census.get('rows'),'unique_arks':census.get('unique_arks'),'total_pages':census.get('total_pages')},
    }
    print('RESULT_JSON='+json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0 if out['status']=='READY' else 3

if __name__=='__main__': raise SystemExit(main())
