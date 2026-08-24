#!/usr/bin/env python3
import collections, itertools, json, pathlib

exact=json.loads(pathlib.Path('control/m5_exact_evidence_result.json').read_text('utf-8'))
analysis=json.loads(pathlib.Path('control/m5_evidence_analysis.json').read_text('utf-8'))
rows=exact.get('rows',[])
terms=exact.get('terms',[])

edge_rows=collections.defaultdict(list)
for r in rows:
    present=sorted(set(r.get('matched_terms',[])))
    for a,b in itertools.combinations(present,2):
        key=(a,b)
        if len(edge_rows[key])<8:
            edge_rows[key].append({
                'source':r.get('source'), 'file':r.get('file'), 'row':r.get('row'),
                'row_sha256':r.get('row_sha256')
            })

nodes=[{'id':t,'type':'research_term'} for t in terms]
edges=[]
for p in analysis.get('pair_counts',[]):
    key=tuple(sorted((p['a'],p['b'])))
    edges.append({
      'source':key[0], 'target':key[1], 'relation':'TEXTUAL_COOCCURRENCE',
      'rows':int(p['rows']), 'evidence_examples':edge_rows.get(key,[]),
      'truth_status':'FACT_TEXTUAL_COOCCURRENCE_ONLY'
    })
edges.sort(key=lambda x:(-x['rows'],x['source'],x['target']))

graph={
  'format':'osr-graph-prep/v1',
  'source_run_id':exact.get('run_id'),
  'nodes':nodes,
  'edges':edges,
  'edge_semantics':'An edge means exact-row textual co-occurrence in retrieved evidence. It does not assert historical identity, causality, chronology, or mythic equivalence.',
  'next_gate':'source/genre/date audit before any edge can be promoted beyond textual co-occurrence'
}
pathlib.Path('control/m6_graph_prep.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2)+'\n','utf-8')
print(json.dumps({'status':'PASS','nodes':len(nodes),'edges':len(edges)},ensure_ascii=False))
