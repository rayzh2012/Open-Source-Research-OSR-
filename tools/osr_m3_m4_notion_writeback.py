#!/usr/bin/env python3
import json, os, pathlib

try:
    import requests
except Exception:
    requests = None

ROOT=pathlib.Path('control')
status=json.loads((ROOT/'feature_extraction_status.json').read_text('utf-8'))
agg_path=ROOT/'research_aggregation_v1.json'
agg=json.loads(agg_path.read_text('utf-8')) if agg_path.exists() else {}

run_id=status.get('run_id','unknown')
text=(
    f"【OSR M3/M4】{run_id} | M3={status.get('status','UNKNOWN')} | "
    f"workers={status.get('workers_completed','?')}/{status.get('expected_workers','?')} | "
    f"shards={status.get('shards_scanned','?')}/{status.get('expected_shards','?')} | "
    f"failed_shards={status.get('failed_shards_count','?')} | "
    f"GiB={status.get('aggregate_download_GiB','?')} | "
    f"M4={'PASS' if agg and agg.get('inputs',{}).get('feature_run_id')==run_id else 'NOT_READY'}"
)

payload={
    'format':'osr-m3-m4-notion-writeback/v1',
    'run_id':run_id,
    'summary_text':text,
    'm3_status':status.get('status'),
    'm4_ready':bool(agg and agg.get('inputs',{}).get('feature_run_id')==run_id),
    'direct_sync_attempted':False,
    'direct_sync_status':'NOT_ATTEMPTED',
}

token=os.getenv('NOTION_TOKEN'); page_id=os.getenv('NOTION_PAGE_ID')
if token and page_id and requests is not None:
    payload['direct_sync_attempted']=True
    body={'children':[{'object':'block','type':'paragraph','paragraph':{'rich_text':[{'type':'text','text':{'content':text}}]}}]}
    r=requests.patch(
        f'https://api.notion.com/v1/blocks/{page_id}/children',
        headers={'Authorization':f'Bearer {token}','Notion-Version':'2022-06-28','Content-Type':'application/json'},
        json=body, timeout=30,
    )
    payload['direct_sync_status']='PASS' if r.ok else f'HTTP_{r.status_code}'
    if not r.ok: payload['direct_sync_error']=(r.text or '')[:800]
else:
    payload['direct_sync_status']='PAYLOAD_ONLY_NO_SECRET'

out=ROOT/'m3_m4_notion_writeback.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps(payload,ensure_ascii=False))
if payload['direct_sync_attempted'] and payload['direct_sync_status']!='PASS':
    raise SystemExit(4)
