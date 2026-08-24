#!/usr/bin/env python3
import collections, itertools, json, pathlib

exact=json.loads(pathlib.Path('control/m5_exact_evidence_result.json').read_text('utf-8'))
analysis=json.loads(pathlib.Path('control/m5_evidence_analysis.json').read_text('utf-8'))
rows=exact.get('rows',[])
terms=exact.get('terms',[])

# Default graph edges use only terms co-present in the stored local evidence snippet.
edge_rows=collections.defaultdict(list)
for r in rows:
    snippet=r.get('snippet') or ''
    present=sorted(t for t in terms if t in snippet)
    for a,b in itertools.combinations(present,2):
        key=(a,b)
        if len(edge_rows[key])<8:
            edge_rows[key].append({
                'source':r.get('source'),
                'file':r.get('file'),
                'row':r.get('row'),
                'row_sha256':r.get('row_sha256')
            })

row_pairs={(p['a'],p['b']):int(p['rows']) for p in analysis.get('row_level',{}).get('pair_counts',[])}
local_pairs=analysis.get('local_window',{}).get('pair_counts',[])

nodes=[{'id':t,'type':'research_term'} for t in terms]
edges=[]
for p in local_pairs:
    key=tuple(sorted((p['a'],p['b'])))
    local_n=int(p['rows'])
    row_n=row_pairs.get(key)
    edges.append({
        'source':key[0],
        'target':key[1],
        'relation':'TEXTUAL_LOCAL_COOCCURRENCE',
        'local_window_rows':local_n,
        'whole_row_rows':row_n,
        'locality_retention':round(local_n/row_n,6) if row_n else None,
        'evidence_examples':edge_rows.get(key,[]),
        'truth_status':'TEXTUAL_LOCAL_ONLY'
    })
edges.sort(key=lambda x:(-x['local_window_rows'],x['source'],x['target']))

graph={
    'format':'osr-graph-prep/v2',
    'source_run_id':exact.get('run_id'),
    'nodes':nodes,
    'edges':edges,
    'default_evidence_scope':'stored_local_window',
    'whole_row_background_only':True,
    'edge_semantics':'Edge means local textual co-presence in the stored evidence window only; it does not assert identity, causality, chronology, prevalence, or historical truth.',
    'selection_warning':'Rows came from router-ranked top shards with per-shard caps, so edge counts are not full-corpus prevalence estimates.',
    'next_gate':'Audit source identity, edition/date, genre, and independent corroboration before any stronger interpretation.'
}
pathlib.Path('control/m6_graph_prep.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps({'status':'PASS','nodes':len(nodes),'edges':len(edges),'scope':'local_window'},ensure_ascii=False))
