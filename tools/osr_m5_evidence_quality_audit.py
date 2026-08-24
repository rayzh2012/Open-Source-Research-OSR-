#!/usr/bin/env python3
import collections, hashlib, json, pathlib, re

p=pathlib.Path('control/m5_exact_evidence_result.json')
data=json.loads(p.read_text('utf-8'))
rows=data.get('rows',[])
terms=data.get('terms',[])

hashes=[r.get('row_sha256') for r in rows if r.get('row_sha256')]
unique_hashes=set(hashes)
shards={(r.get('source'),r.get('file')) for r in rows}
sources={r.get('source') for r in rows if r.get('source')}

# Heuristic cues only; never truth labels.
modern_markers=['百度','知乎','网友','网络','小说','章节','作者','出版社','电视剧','电影','游戏','维基','百科','论坛','博客','转载','现代','当代']
classical_markers=['曰','传曰','史记','山海经','淮南子','尚书','楚辞','列子','庄子','左传','国语']
modern_hits=0
classical_hits=0
row_density=[]
local_density=[]

sig_counts=collections.Counter()
for r in rows:
    snippet=r.get('snippet') or ''
    if any(x in snippet for x in modern_markers): modern_hits+=1
    if any(x in snippet for x in classical_markers): classical_hits+=1
    row_density.append(int(r.get('matched_term_count') or len(r.get('matched_terms') or [])))
    # Prefer selector-computed local_terms so QA measures the same evidence window used downstream.
    local_terms=r.get('local_terms')
    if isinstance(local_terms,list):
        local_density.append(len(set(local_terms)))
    else:
        local_density.append(sum(1 for t in terms if t in snippet))
    norm=re.sub(r'\s+','',snippet)
    if norm:
        sig_counts[hashlib.sha256(norm.encode()).hexdigest()]+=1

repeated_snippet_rows=sum(n for n in sig_counts.values() if n>1)
n=len(rows)
thresholds=[2,3,4,5]
threshold_metrics={}
for k in thresholds:
    row_ge=sum(1 for x in row_density if x>=k)
    local_ge=sum(1 for x in local_density if x>=k)
    retention=(local_ge/row_ge) if row_ge else None
    # A local window is a subset of the row; if this invariant fails the extractor/QA contract is broken.
    invariant_ok=(local_ge <= row_ge)
    threshold_metrics[str(k)]={
        'row_ge_k':row_ge,
        'local_ge_k':local_ge,
        'retention':round(retention,6) if retention is not None else None,
        'subset_invariant_ok':invariant_ok,
    }

risk_flags=[]
if len(sources)<2: risk_flags.append('single_source_corpus_in_retrieved_sample')
if repeated_snippet_rows: risk_flags.append('repeated_snippets_present')
if len(unique_hashes)<n: risk_flags.append('exact_duplicate_rows_present')
for k,m in threshold_metrics.items():
    if not m['subset_invariant_ok']:
        risk_flags.append(f'locality_subset_invariant_failed_ge_{k}')
    elif m['row_ge_k'] and m['local_ge_k'] < m['row_ge_k']:
        risk_flags.append(f'row_level_inflation_vs_local_window_ge_{k}')
risk_flags.append('top_shard_bounded_sampling_not_prevalence_estimate')
risk_flags.append('source_identity_date_genre_not_yet_fully_resolved')

audit={
  'format':'osr-m5-evidence-quality-audit/v2.1',
  'run_id':data.get('run_id'),
  'rows':n,
  'query_term_count':len(terms),
  'unique_full_row_hashes':len(unique_hashes),
  'exact_row_duplicate_fraction':round(1-len(unique_hashes)/n,6) if n else None,
  'unique_shards':len(shards),
  'source_corpora':sorted(sources),
  'source_corpus_count':len(sources),
  'modern_marker_rows':modern_hits,
  'classical_marker_rows':classical_hits,
  'repeated_snippet_rows':repeated_snippet_rows,
  'mean_row_matched_terms':round(sum(row_density)/len(row_density),3) if row_density else 0,
  'mean_local_matched_terms':round(sum(local_density)/len(local_density),3) if local_density else 0,
  'locality_thresholds':threshold_metrics,
  'locality_contract':'local window is a subset of the source row; for every k, local_ge_k must be <= row_ge_k',
  'selection_bias':{
    'router_top_n_shards':data.get('top_n_shards'),
    'bounded_rows_per_shard':True,
    'prevalence_inference_allowed':False
  },
  'risk_flags':risk_flags,
  'quality_gate':{
    'local_window_required_for_default_graph':True,
    'requires_independent_source_corpora':True,
    'requires_source_identity_audit':True,
    'requires_date_genre_audit':True,
    'historical_fact_upgrade_allowed':False
  },
  'note':'Marker counts are heuristic contamination cues only. This sample is deliberately enriched by router rank and per-shard caps; it cannot estimate full-corpus prevalence. Source identity, edition, date, genre, and independent-source corroboration remain mandatory for historical inference.'
}
pathlib.Path('control/m5_evidence_quality_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps({'status':'PASS','run_id':data.get('run_id'),'rows':n,'unique_hashes':len(unique_hashes),'unique_shards':len(shards),'thresholds':threshold_metrics,'risk_flags':risk_flags},ensure_ascii=False))
