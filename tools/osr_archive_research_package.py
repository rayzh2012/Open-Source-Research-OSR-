#!/usr/bin/env python3
import hashlib, json, pathlib, shutil

ROOT=pathlib.Path('control')
RUNS=ROOT/'research_runs'

spec={
  'exact_evidence.json': (ROOT/'m5_exact_evidence_result.json','run_id'),
  'exact_evidence_summary.json': (ROOT/'m5_exact_evidence_summary.json','run_id'),
  'evidence_analysis.json': (ROOT/'m5_evidence_analysis.json','run_id'),
  'evidence_quality_audit.json': (ROOT/'m5_evidence_quality_audit.json','run_id'),
  'source_chronology_audit.json': (ROOT/'m5_source_chronology_audit.json','run_id'),
  'graph_prep.json': (ROOT/'m6_graph_prep.json','source_run_id'),
  'notion_writeback.json': (ROOT/'notion_writeback_latest.json','run_id'),
}

objs={}
for out_name,(src,key) in spec.items():
    if not src.exists():
        raise SystemExit(f'missing required component: {src}')
    try:
        obj=json.loads(src.read_text('utf-8'))
    except Exception as e:
        raise SystemExit(f'invalid JSON {src}: {e}')
    objs[out_name]=(src,key,obj)

run_id=objs['exact_evidence_summary.json'][2].get('run_id')
if not run_id:
    raise SystemExit('missing run_id in exact summary')
if any(x in run_id for x in ('/','\\','..')):
    raise SystemExit(f'unsafe run_id: {run_id}')

mismatches={}
for out_name,(src,key,obj) in objs.items():
    got=obj.get(key)
    if got != run_id:
        mismatches[out_name]={'key':key,'expected':run_id,'got':got}
if mismatches:
    print(json.dumps({'status':'ARCHIVE_FAILED','run_id':run_id,'mismatches':mismatches},ensure_ascii=False,indent=2))
    raise SystemExit(5)

run_dir=RUNS/run_id
run_dir.mkdir(parents=True,exist_ok=True)
files=[]
for out_name,(src,key,obj) in objs.items():
    dst=run_dir/out_name
    shutil.copyfile(src,dst)
    b=dst.read_bytes()
    files.append({'name':out_name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'id_key':key,'run_id':obj.get(key)})

manifest={
  'format':'osr-research-package-manifest/v1',
  'status':'COMPLETE',
  'run_id':run_id,
  'required_components':list(spec),
  'component_count':len(files),
  'components':files,
  'rules':{
    'all_component_run_ids_match':True,
    'exact_evidence_required':True,
    'analysis_required':True,
    'quality_required':True,
    'source_chronology_required':True,
    'graph_required':True,
    'notion_writeback_payload_required':True,
  }
}
(run_dir/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps({'status':'ARCHIVE_COMPLETE','run_id':run_id,'components':len(files),'manifest':str(run_dir/'run_manifest.json')},ensure_ascii=False))
