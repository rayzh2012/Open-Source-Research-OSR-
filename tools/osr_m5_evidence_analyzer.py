#!/usr/bin/env python3
import collections, hashlib, itertools, json, pathlib, re

SRC=pathlib.Path('control/m5_exact_evidence_result.json')
data=json.loads(SRC.read_text('utf-8'))
rows=data.get('rows',[])
terms=data.get('terms',[])

PATTERNS={
  'gonggong_buzhou_collision':['共工','不周山'],
  'nuwa_flood':['女娲','洪水'],
  'nuwa_buzhou':['女娲','不周山'],
  'gonggong_flood':['共工','洪水'],
  'flood_control':['洪水','治水'],
  'five_term_fusion':['女娲','共工','洪水','治水','不周山'],
}
MODERN_MARKERS=['百度','知乎','网友','网络','小说','章节','作者','出版社','电视剧','电影','游戏','维基','百科','论坛','博客','转载','现代','当代']
CLASSICAL_MARKERS=['曰','传曰','史记','山海经','淮南子','尚书','楚辞','列子','庄子','左传','国语']

def analyze_sets(source_sets):
    termsets=collections.Counter(); pairs=collections.Counter(); patterns=collections.Counter()
    for present in source_sets:
        present=tuple(sorted(set(present))); termsets[present]+=1
        for a,b in itertools.combinations(present,2): pairs[(a,b)]+=1
        s=set(present)
        for pid,need in PATTERNS.items():
            if set(need).issubset(s): patterns[pid]+=1
    return termsets,pairs,patterns

def cue_class(snippet):
    modern=[m for m in MODERN_MARKERS if m in snippet]; classical=[m for m in CLASSICAL_MARKERS if m in snippet]
    if modern and classical: label='mixed_cues'
    elif modern: label='modern_cues'
    elif classical: label='classical_cues'
    else: label='uncued'
    return label,modern[:6],classical[:6]

def ex_record(r,local_present,label,modern,classical):
    return {'source':r.get('source'),'file':r.get('file'),'row':r.get('row'),'row_sha256':r.get('row_sha256'),'local_terms':local_present,'cue_class':label,'modern_cues':modern,'classical_cues':classical,'snippet':r.get('snippet') or ''}

row_sets=[]; local_sets=[]; local_spans=[]
unique_hashes=set(); shard_counts=collections.Counter(); snippet_sigs=collections.Counter()
modern_rows=0; classical_rows=0
pair_candidates=collections.defaultdict(list); pair_shard_counts=collections.defaultdict(collections.Counter)

for r in rows:
    row_present=sorted(set(r.get('matched_terms',[]))); snippet=r.get('snippet') or ''
    local_present=sorted(t for t in terms if t in snippet)
    row_sets.append(row_present); local_sets.append(local_present)
    unique_hashes.add(r.get('row_sha256')); shard_counts[(r.get('source'),r.get('file'))]+=1
    norm=re.sub(r'\s+','',snippet)
    if norm: snippet_sigs[hashlib.sha256(norm.encode()).hexdigest()]+=1
    label,modern,classical=cue_class(snippet)
    if modern: modern_rows+=1
    if classical: classical_rows+=1
    positions=[]
    for t in local_present:
        p=snippet.find(t)
        if p>=0: positions.append((p,p+len(t)))
    if len(positions)>=2: local_spans.append(max(e for _,e in positions)-min(s for s,_ in positions))
    for a,b in itertools.combinations(local_present,2):
        key=(a,b); shard=(r.get('source'),r.get('file'))
        pair_shard_counts[key][shard]+=1
        pair_candidates[key].append(ex_record(r,local_present,label,modern,classical))

row_termsets,row_pairs,row_patterns=analyze_sets(row_sets); local_termsets,local_pairs,local_patterns=analyze_sets(local_sets)
matched_hist=collections.Counter(len(x) for x in row_sets); local_hist=collections.Counter(len(x) for x in local_sets)
retention=collections.Counter((len(a),len(b)) for a,b in zip(row_sets,local_sets)); n=len(rows)
repeat_snippet_rows=sum(v for v in snippet_sigs.values() if v>1)
local_two_plus=sum(1 for x in local_sets if len(x)>=2); row_two_plus=sum(1 for x in row_sets if len(x)>=2)
local_four_plus=sum(1 for x in local_sets if len(x)>=4); local_five=sum(1 for x in local_sets if len(x)==5)
row_four_plus=sum(1 for x in row_sets if len(x)>=4); row_five=sum(1 for x in row_sets if len(x)==5)

pair_examples=[]
for key,count in local_pairs.most_common():
    # Diversity-first digest: first take one example per shard, then fill remaining slots.
    chosen=[]; chosen_hashes=set(); seen_shards=set()
    for e in pair_candidates[key]:
        shard=(e['source'],e['file'])
        if shard in seen_shards: continue
        chosen.append(e); chosen_hashes.add(e['row_sha256']); seen_shards.add(shard)
        if len(chosen)>=5: break
    if len(chosen)<5:
        for e in pair_candidates[key]:
            if e['row_sha256'] in chosen_hashes: continue
            chosen.append(e); chosen_hashes.add(e['row_sha256'])
            if len(chosen)>=5: break
    pair_examples.append({
        'a':key[0],'b':key[1],'local_rows':count,'unique_shards':len(pair_shard_counts[key]),
        'per_shard_counts':[{'source':s,'file':f,'rows':v} for (s,f),v in pair_shard_counts[key].most_common()],
        'examples':chosen
    })

analysis={
  'format':'osr-m5-evidence-analysis/v2.2','run_id':data.get('run_id'),'rows_found':n,
  'unique_row_hashes':len(unique_hashes),'exact_row_duplicate_fraction':round(1-len(unique_hashes)/n,6) if n else None,
  'repeated_snippet_rows':repeat_snippet_rows,'shards_with_evidence':len(shard_counts),'source_corpora':sorted({r.get('source') for r in rows if r.get('source')}),
  'selection_design':{'router_ranked_top_shards':data.get('top_n_shards'),'max_rows_per_shard':'bounded by retrieval request','representative_prevalence_sample':False,'warning':'Counts describe the bounded high-yield retrieval sample, not prevalence in the full corpus.'},
  'row_level':{'definition':'terms anywhere in the full source row/document','matched_term_count_histogram':{str(k):v for k,v in sorted(matched_hist.items())},'four_plus_term_rows':row_four_plus,'five_term_rows':row_five,'termset_counts':[{'terms':list(k),'rows':v} for k,v in row_termsets.most_common()],'pair_counts':[{'a':a,'b':b,'rows':v} for (a,b),v in row_pairs.most_common()],'pattern_counts':dict(row_patterns)},
  'local_window':{'definition':'terms physically present in the stored ~520-character snippet centered near the earliest hit','two_plus_term_rows':local_two_plus,'four_plus_term_rows':local_four_plus,'five_term_rows':local_five,'two_plus_retention_vs_row':round(local_two_plus/row_two_plus,6) if row_two_plus else None,'four_plus_retention_vs_row':round(local_four_plus/row_four_plus,6) if row_four_plus else None,'five_term_retention_vs_row':round(local_five/row_five,6) if row_five else None,'matched_term_count_histogram':{str(k):v for k,v in sorted(local_hist.items())},'termset_counts':[{'terms':list(k),'rows':v} for k,v in local_termsets.most_common()],'pair_counts':[{'a':a,'b':b,'rows':v,'unique_shards':len(pair_shard_counts[(a,b)])} for (a,b),v in local_pairs.most_common()],'pair_evidence_digest':pair_examples,'pattern_counts':dict(local_patterns),'median_observed_term_span_chars':sorted(local_spans)[len(local_spans)//2] if local_spans else None,'max_observed_term_span_chars':max(local_spans) if local_spans else None},
  'locality_retention_matrix':[{'row_terms':a,'local_terms':b,'rows':v} for (a,b),v in sorted(retention.items())],
  'quality_signals':{'modern_marker_rows':modern_rows,'classical_marker_rows':classical_rows,'heuristic_only':True,'requires_source_identity_date_genre_audit':True},
  'top_shards':[{'source':s,'file':f,'rows':v} for (s,f),v in shard_counts.most_common(20)],
  'promotion_gate':{'graph_default_signal':'local_window.pair_counts','row_level_edges_allowed_by_default':False,'historical_fact_upgrade_allowed':False},
  'interpretation_guardrail':'Row-level co-presence and local-window co-occurrence are different evidence strengths. Pair examples are sampled diversity-first across shards. Source identity, edition/date, genre, duplication, and independent-source audit are required before historical promotion.'
}
pathlib.Path('control/m5_evidence_analysis.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps({'status':'PASS','rows':n,'local_pairs':len(local_pairs),'digest_sampling':'diversity_first'},ensure_ascii=False))
