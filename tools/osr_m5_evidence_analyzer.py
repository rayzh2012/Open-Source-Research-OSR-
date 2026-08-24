#!/usr/bin/env python3
import collections, itertools, json, pathlib

SRC=pathlib.Path('control/m5_exact_evidence_result.json')
out=json.loads(SRC.read_text('utf-8'))
rows=out.get('rows',[])
terms=out.get('terms',[])

termset_counts=collections.Counter()
pair_counts=collections.Counter()
shard_counts=collections.Counter()
unique_hashes=set()
pattern_counts=collections.Counter()

PATTERNS={
  'gonggong_buzhou_collision':['共工','不周山'],
  'nuwa_flood':['女娲','洪水'],
  'nuwa_buzhou':['女娲','不周山'],
  'gonggong_flood':['共工','洪水'],
  'flood_control':['洪水','治水'],
  'five_term_fusion':['女娲','共工','洪水','治水','不周山'],
}

for r in rows:
    present=tuple(sorted(set(r.get('matched_terms',[]))))
    termset_counts[present]+=1
    unique_hashes.add(r.get('row_sha256'))
    shard_counts[(r.get('source'),r.get('file'))]+=1
    for a,b in itertools.combinations(present,2):
        pair_counts[(a,b)]+=1
    s=set(present)
    for pid,need in PATTERNS.items():
        if set(need).issubset(s):
            pattern_counts[pid]+=1

analysis={
  'format':'osr-m5-evidence-analysis/v1',
  'run_id':out.get('run_id'),
  'rows_found':len(rows),
  'unique_row_hashes':len(unique_hashes),
  'shards_with_evidence':len(shard_counts),
  'termset_counts':[{'terms':list(k),'rows':v} for k,v in termset_counts.most_common()],
  'pair_counts':[{'a':a,'b':b,'rows':n} for (a,b),n in pair_counts.most_common()],
  'pattern_counts':dict(pattern_counts),
  'top_shards':[{'source':s,'file':f,'rows':n} for (s,f),n in shard_counts.most_common(20)],
  'interpretation_guardrail':'These are exact-row textual co-occurrence patterns, not historical truth claims. Source identity/date/genre audit is required before upgrading any hypothesis.'
}
pathlib.Path('control/m5_evidence_analysis.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps({'status':'PASS','rows':len(rows),'patterns':dict(pattern_counts)},ensure_ascii=False))
