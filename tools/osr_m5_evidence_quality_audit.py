#!/usr/bin/env python3
import collections, hashlib, json, pathlib, re

p=pathlib.Path('control/m5_exact_evidence_result.json')
data=json.loads(p.read_text('utf-8'))
rows=data.get('rows',[])

hashes=[r.get('row_sha256') for r in rows if r.get('row_sha256')]
unique_hashes=set(hashes)
shards={(r.get('source'),r.get('file')) for r in rows}
sources={r.get('source') for r in rows if r.get('source')}

# Heuristic only: flag likely modern/web/editorial contexts; never use as a truth label.
modern_markers=['百度','知乎','网友','网络','小说','章节','作者','出版社','电视剧','电影','游戏','维基','百科','论坛','博客','转载','现代','当代']
classical_markers=['曰','传曰','史记','山海经','淮南子','尚书','楚辞','列子','庄子','左传','国语']
modern_hits=0; classical_hits=0
term_density=[]
for r in rows:
    s=r.get('snippet') or ''
    if any(x in s for x in modern_markers): modern_hits+=1
    if any(x in s for x in classical_markers): classical_hits+=1
    term_density.append(int(r.get('matched_term_count') or 0))

# repeated snippets may differ in full-row hash; use normalized snippet signature as a second duplicate signal
sig_counts=collections.Counter()
for r in rows:
    s=re.sub(r'\s+','',r.get('snippet') or '')
    sig=hashlib.sha256(s.encode()).hexdigest() if s else ''
    if sig: sig_counts[sig]+=1
repeated_snippet_rows=sum(n for n in sig_counts.values() if n>1)

n=len(rows)
audit={
  'format':'osr-m5-evidence-quality-audit/v1',
  'run_id':data.get('run_id'),
  'rows':n,
  'unique_full_row_hashes':len(unique_hashes),
  'exact_row_duplicate_fraction':round(1-len(unique_hashes)/n,6) if n else None,
  'unique_shards':len(shards),
  'source_corpora':sorted(sources),
  'modern_marker_rows':modern_hits,
  'classical_marker_rows':classical_hits,
  'repeated_snippet_rows':repeated_snippet_rows,
  'mean_matched_terms':round(sum(term_density)/len(term_density),3) if term_density else 0,
  'quality_gate':{
    'requires_source_identity_audit':True,
    'requires_date_genre_audit':True,
    'historical_fact_upgrade_allowed':False
  },
  'note':'Marker counts are heuristic contamination signals only. They do not classify a row as ancient or modern. Exact source identity, edition, date, and genre must be audited before historical inference.'
}
pathlib.Path('control/m5_evidence_quality_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps({'status':'PASS','rows':n,'unique_hashes':len(unique_hashes),'unique_shards':len(shards)},ensure_ascii=False))
