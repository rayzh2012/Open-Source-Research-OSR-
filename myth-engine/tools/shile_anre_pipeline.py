#!/usr/bin/env python3
import argparse, csv, hashlib, json
from pathlib import Path

FIELDS=["phonetic_fit","semantic_fit","chronology_fit","geography_fit","morphology_fit","source_independence","holdout_bonus"]

def load_json(p):
    with open(p,encoding="utf-8") as f: return json.load(f)

def weighted_score(h,w):
    pos=sum(float(h.get(k,0))*float(w.get(k,0)) for k in FIELDS)
    penalty=float(h.get("patch_cost",0))*float(w.get("patch_cost_penalty",0))
    return round(pos-penalty,4)

def dependency_collapse(witnesses):
    groups={}
    for x in witnesses:
        groups.setdefault(x.get("dependency_group",x["id"]),[]).append(x["id"])
    return groups

def variant_graph(witnesses):
    out=[]
    base=witnesses[0]["text"]
    for x in witnesses:
        text=x["text"]
        diffs=[]
        maxlen=max(len(base),len(text))
        for i in range(maxlen):
            a=base[i] if i<len(base) else "∅"
            b=text[i] if i<len(text) else "∅"
            if a!=b: diffs.append({"pos":i,"base":a,"variant":b})
        out.append({"id":x["id"],"title":x["title"],"label":x["label"],"text":text,"diffs_vs_base":diffs})
    return out

def write_csv(path,rows,fields):
    with open(path,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--query-pack",required=True)
    ap.add_argument("--output-dir",required=True)
    a=ap.parse_args()
    q=load_json(a.query_pack); out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)

    groups=dependency_collapse(q["witnesses"])
    vg=variant_graph(q["witnesses"])
    (out/"variant_graph.json").write_text(json.dumps({"dependency_groups":groups,"variants":vg},ensure_ascii=False,indent=2),encoding="utf-8")

    scores=[]
    for h in q["hypotheses"]:
        row=dict(h); row["anre_score"]=weighted_score(h,q["score_weights"]); scores.append(row)
    scores.sort(key=lambda x:x["anre_score"],reverse=True)
    fields=["id","name","status","anre_score","phonetic_fit","semantic_fit","chronology_fit","geography_fit","morphology_fit","source_independence","holdout_bonus","patch_cost"]
    write_csv(out/"hypothesis_matrix.csv",scores,fields)

    queue=[]
    for i,t in enumerate(q["priority_terms"],1):
        queue.append({"priority":f"P{i:02d}","term":t["term"],"target_period":t["target_period"],"task":t["task"],"status":"TODO_YEAR_SOUND"})
    write_csv(out/"phonology_queue.csv",queue,["priority","term","target_period","task","status"])

    manifest={
      "model_version":q["model_version"],
      "research_question":q["research_question"],
      "witness_count":len(q["witnesses"]),
      "dependency_group_count":len(groups),
      "hypothesis_count":len(scores),
      "priority_term_count":len(queue),
      "top_model":scores[0]["name"] if scores else None,
      "top_score":scores[0]["anre_score"] if scores else None,
      "note":"Scores are diagnostic priors for workflow testing, not historical verdicts. Replace seeded priors with evidence-derived values as the corpus grows."
    }
    raw=json.dumps(q,ensure_ascii=False,sort_keys=True).encode()
    manifest["query_pack_sha256"]=hashlib.sha256(raw).hexdigest()
    (out/"run_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"next_search.json").write_text(json.dumps({"highest_information_gain":[q["contradictions"][0],{"id":"IG_4C","claim":"Build a 300-400 CE Chinese transcription lattice for every character in the couplet and priority terms.","action":"record multiple reconstruction systems side-by-side; never collapse uncertainty prematurely"},{"id":"IG_BLIND","claim":"Blind-fit candidate language models before revealing traditional gloss alignment.","action":"score whole-phrase morphology and chronology before lexical cherry-picking"}]},ensure_ascii=False,indent=2),encoding="utf-8")

    lines=[f"# Shile ANRE run — {q['model_version']}","",f"Question: {q['research_question']}","","## Dependency collapse"]
    for g,ids in groups.items(): lines.append(f"- {g}: {', '.join(ids)}")
    lines += ["","## Hypothesis diagnostic order"]
    for r in scores: lines.append(f"- {r['name']}: {r['anre_score']:.4f} ({r['status']})")
    lines += ["","## Contradictions"]
    for c in q["contradictions"]: lines.append(f"- {c['id']}: {c['claim']} → {c['action']}")
    lines += ["","## Rule","A high score does not promote a hypothesis to FACT. Promotion requires independent historical evidence, chronology fit, and successful holdout tests."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")

if __name__=="__main__": main()
