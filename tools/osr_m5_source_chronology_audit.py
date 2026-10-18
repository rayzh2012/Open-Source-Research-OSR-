#!/usr/bin/env python3
# v1.0.1: explicit trigger after workflow installation; cue-based routing only.
import collections, json, pathlib, re

SRC=pathlib.Path('control/m5_exact_evidence_result.json')
OUT=pathlib.Path('control/m5_source_chronology_audit.json')
ARCHIVE=pathlib.Path('control/research_runs')
data=json.loads(SRC.read_text('utf-8'))
rows=data.get('rows',[])

YEAR_RE=re.compile(r'(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)')
BOOK_RE=re.compile(r'《([^》]{1,80})》')
JOURNAL_CUES=['摘要','关键词','中图分类号','文献标志码','文章编号','参考文献','学报','DOI','基金项目']
FICTION_CUES=['第1章','第一章','小说','网文','起点','纵横','晋江','番茄','作者说','本章完']
ETHNO_CUES=['民间故事','口述','调查','田野','民族','民歌','古歌','传说','仪式','祭祀','采录','访谈']
CLASSICAL_CUES=['史记','集解','正义','索隐','山海经','淮南子','尚书','楚辞','列子','庄子','左传','国语','太平御览','艺文类聚','路史','帝王世纪','汲冢纪年']
TARGET_FUSION={'共工','不周山','女娲','补天'}

def hits(text,cues): return [x for x in cues if x in text]

audited=[]
for r in rows:
    text='\n'.join([str(r.get('document_head') or ''),str(r.get('snippet') or '')])
    meta=r.get('metadata') or {}
    meta_text=json.dumps(meta,ensure_ascii=False)
    all_text=text+'\n'+meta_text
    years=sorted(set(int(x) for x in YEAR_RE.findall(all_text)))
    books=[]
    for b in BOOK_RE.findall(all_text):
        if b not in books: books.append(b)
        if len(books)>=12: break
    journal=hits(all_text,JOURNAL_CUES); fiction=hits(all_text,FICTION_CUES)
    ethno=hits(all_text,ETHNO_CUES); classical=hits(all_text,CLASSICAL_CUES)
    local=set(r.get('local_terms') or [t for t in data.get('terms',[]) if t in (r.get('snippet') or '')])
    fusion_count=len(local & TARGET_FUSION)
    if journal: genre='scholarly_secondary_cues'
    elif fiction: genre='modern_fiction_cues'
    elif ethno: genre='ethnographic_or_folklore_cues'
    elif classical: genre='classical_text_or_commentary_cues'
    else: genre='unclassified'
    score=fusion_count*10 + min(len(classical),4)*3 + min(len(books),4)*2 + (2 if ethno else 0) - (6 if fiction else 0)
    audited.append({
      'source':r.get('source'),'file':r.get('file'),'row':r.get('row'),'row_sha256':r.get('row_sha256'),
      'local_terms':sorted(local),'local_span_chars':r.get('local_span_chars'),
      'metadata':meta,'year_hints':years[:10],'work_title_hints':books,
      'genre_cue_class':genre,'journal_cues':journal,'fiction_cues':fiction,
      'ethnographic_cues':ethno,'classical_source_cues':classical,
      'chronology_routing_score':score,
      'snippet':r.get('snippet') or ''
    })

audited.sort(key=lambda x:(-x['chronology_routing_score'],-len(x['local_terms']),x['file'] or '',x['row'] or 0))
classes=collections.Counter(x['genre_cue_class'] for x in audited)
result={
 'format':'osr-m5-source-chronology-audit/v1','run_id':data.get('run_id'),'router_run_id':data.get('router_run_id'),
 'rows_audited':len(audited),'genre_cue_counts':dict(classes),
 'chronology_candidates':audited[:60],
 'rules':{
   'cue_labels_are_not_source_identity':True,
   'year_hints_are_not_document_dates':True,
   'chronology_score_is_routing_only':True,
   'historical_fact_upgrade_allowed':False
 },
 'next_gate':'Resolve exact work/title/author/edition/date for strongest candidates, then compare earliest independent sources before asserting fusion chronology.'
}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
run=data.get('run_id')
if run:
    d=ARCHIVE/run; d.mkdir(parents=True,exist_ok=True)
    (d/'source_chronology_audit.json').write_text(OUT.read_text('utf-8'),'utf-8')
print(json.dumps({'status':'PASS','run_id':run,'rows':len(audited),'classes':dict(classes)},ensure_ascii=False))
