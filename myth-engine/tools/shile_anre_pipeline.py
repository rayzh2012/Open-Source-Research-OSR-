#!/usr/bin/env python3
import argparse, csv, hashlib, json
from pathlib import Path

FIELDS=["phonetic_fit","semantic_fit","chronology_fit","geography_fit","morphology_fit","source_independence","holdout_bonus"]


def load_json(p):
    with open(p,encoding="utf-8") as f:
        return json.load(f)


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
            if a!=b:
                diffs.append({"pos":i,"base":a,"variant":b})
        out.append({"id":x["id"],"title":x["title"],"label":x["label"],"text":text,"diffs_vs_base":diffs})
    return out


def write_csv(path,rows,fields):
    with open(path,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def resolve_project_file(query_pack_path, rel):
    p=Path(rel)
    if p.is_absolute() and p.exists():
        return p
    if p.exists():
        return p
    repo_root=Path(query_pack_path).resolve().parents[2]
    candidate=repo_root/p
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Cannot resolve phase file: {rel}")


def evidence_score(model, ablation):
    excluded=set(ablation.get("exclude_dimensions",[]))
    include_semantics=bool(ablation.get("include_semantics",False))
    used=[]
    for e in model.get("evidence",[]):
        if e.get("dimension") in excluded:
            continue
        if not e.get("blind",True) and not include_semantics:
            continue
        used.append(e)
    total=sum(int(e.get("value",0)) for e in used)
    return {
        "score": total,
        "support_count": sum(1 for e in used if int(e.get("value",0))>0),
        "challenge_count": sum(1 for e in used if int(e.get("value",0))<0),
        "evidence_count": len(used),
        "used_ids": [e["id"] for e in used]
    }


def run_blind_phase(blind,out):
    models=blind["models"]
    ablations=blind["ablations"]
    by_id={a["id"]:a for a in ablations}
    blind_cfg=by_id["BLIND_ALL"]

    matrix=[]
    for m in models:
        s=evidence_score(m,blind_cfg)
        matrix.append({
            "id":m["id"],
            "name":m["name"],
            "blind_evidence_balance":s["score"],
            "support_count":s["support_count"],
            "challenge_count":s["challenge_count"],
            "evidence_count":s["evidence_count"],
            "published_analysis":" | ".join(m.get("published_analysis",[])),
            "analysis_source":m.get("analysis_source","")
        })
    matrix.sort(key=lambda r:(-int(r["blind_evidence_balance"]),r["id"]))
    write_csv(out/"blind_fit_matrix.csv",matrix,["id","name","blind_evidence_balance","support_count","challenge_count","evidence_count","published_analysis","analysis_source"])

    ablation_rows=[]
    summary={}
    for a in ablations:
        scored=[]
        for m in models:
            s=evidence_score(m,a)
            scored.append((m,s))
        scored.sort(key=lambda ms:(-ms[1]["score"],ms[0]["id"]))
        leaders=[]
        top_score=scored[0][1]["score"] if scored else None
        for rank,(m,s) in enumerate(scored,1):
            ablation_rows.append({
                "ablation":a["id"],
                "description":a["description"],
                "rank":rank,
                "model_id":m["id"],
                "model":m["name"],
                "evidence_balance":s["score"],
                "support_count":s["support_count"],
                "challenge_count":s["challenge_count"],
                "evidence_ids":";".join(s["used_ids"])
            })
            if s["score"]==top_score:
                leaders.append(m["id"])
        summary[a["id"]]={"top_score":top_score,"leaders":leaders,"description":a["description"]}
    write_csv(out/"blind_ablation.csv",ablation_rows,["ablation","description","rank","model_id","model","evidence_balance","support_count","challenge_count","evidence_ids"])
    (out/"ablation_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")

    ledger=[]
    for m in models:
        for e in m.get("evidence",[]):
            ledger.append({
                "model_id":m["id"],
                "model":m["name"],
                "evidence_id":e["id"],
                "dimension":e["dimension"],
                "value":e["value"],
                "blind":str(bool(e.get("blind",True))).lower(),
                "source":e.get("source",""),
                "claim":e.get("claim","")
            })
    write_csv(out/"evidence_ledger.csv",ledger,["model_id","model","evidence_id","dimension","value","blind","source","claim"])
    return matrix,summary


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--query-pack",required=True)
    ap.add_argument("--output-dir",required=True)
    a=ap.parse_args()
    q=load_json(a.query_pack)
    out=Path(a.output_dir)
    out.mkdir(parents=True,exist_ok=True)

    groups=dependency_collapse(q["witnesses"])
    vg=variant_graph(q["witnesses"])
    (out/"variant_graph.json").write_text(json.dumps({"dependency_groups":groups,"variants":vg},ensure_ascii=False,indent=2),encoding="utf-8")

    # Legacy v1.0 weighted priors are retained for comparison only.
    scores=[]
    for h in q["hypotheses"]:
        row=dict(h)
        row["anre_score"]=weighted_score(h,q["score_weights"])
        scores.append(row)
    scores.sort(key=lambda x:x["anre_score"],reverse=True)
    fields=["id","name","status","anre_score","phonetic_fit","semantic_fit","chronology_fit","geography_fit","morphology_fit","source_independence","holdout_bonus","patch_cost"]
    write_csv(out/"hypothesis_matrix.csv",scores,fields)

    queue=[]
    for i,t in enumerate(q["priority_terms"],1):
        queue.append({"priority":f"P{i:02d}","term":t["term"],"target_period":t["target_period"],"task":t["task"],"status":"TODO_YEAR_SOUND"})
    write_csv(out/"phonology_queue.csv",queue,["priority","term","target_period","task","status"])

    # Phase 2: published reconstruction lattice + gloss-hidden evidence balance.
    phase=q.get("phase2_files",{})
    lattice=load_json(resolve_project_file(a.query_pack,phase["phonology_lattice"]))
    blind=load_json(resolve_project_file(a.query_pack,phase["blind_candidates"]))
    lattice_rows=[]
    for r in lattice["rows"]:
        lattice_rows.append({
            "position":r["position"],"char":r["char"],
            "shimunek2015":r["shimunek2015"],"vovin2016":r["vovin2016"],
            "agreement":r["agreement"],"note":r["note"]
        })
    write_csv(out/"phonology_lattice_4c.csv",lattice_rows,["position","char","shimunek2015","vovin2016","agreement","note"])
    blind_matrix,ablation_summary=run_blind_phase(blind,out)

    major_div=[r for r in lattice_rows if r["agreement"]=="MAJOR_DIVERGENCE"]
    blind_leader=blind_matrix[0] if blind_matrix else None
    manifest={
      "model_version":q["model_version"],
      "research_question":q["research_question"],
      "witness_count":len(q["witnesses"]),
      "dependency_group_count":len(groups),
      "hypothesis_count":len(scores),
      "priority_term_count":len(queue),
      "legacy_top_model":scores[0]["name"] if scores else None,
      "legacy_top_score":scores[0]["anre_score"] if scores else None,
      "blind_top_model":blind_leader["name"] if blind_leader else None,
      "blind_evidence_balance":blind_leader["blind_evidence_balance"] if blind_leader else None,
      "lattice_major_divergence_count":len(major_div),
      "lattice_major_divergence_chars":[r["char"] for r in major_div],
      "ablation_summary":ablation_summary,
      "note":"Legacy weighted scores and v1.1 evidence-balance totals are diagnostic workflow outputs, not historical verdicts or probabilities. Promotion requires independent evidence and holdout stability."
    }
    raw=json.dumps(q,ensure_ascii=False,sort_keys=True).encode()
    manifest["query_pack_sha256"]=hashlib.sha256(raw).hexdigest()
    (out/"run_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")

    next_search={"highest_information_gain":[
        {"id":"IG_GU","claim":"谷 is the only character with a major reconstruction divergence between the two published phrase analyses (Shimunek: luk; Vovin: kok).","action":"Resolve 谷 with independent Later Han / Northern EMC evidence and edition-specific phonology before allowing either candidate model to choose its preferred reading."},
        {"id":"IG_MORPH","claim":"Old Arin leads the blind evidence ledger, but the NO_MORPHOLOGY ablation is designed to test whether that lead collapses when morphology is removed.","action":"Verify every proposed Arin morpheme, especially -taŋ and the internal verb-template slots, against independently attested Arin/Yeniseian paradigms rather than the couplet analysis itself."},
        {"id":"IG_TURKIC_CHANNEL","claim":"The Shimunek Turkic parse contains explicit reconstruction costs including a zero-mapped 支 and acknowledged vowel-harmony/accusative issues.","action":"Re-run its segmentation against both published Chinese reconstruction layers and count zero mappings, compression/expansion and hypothetical morphology explicitly."},
        {"id":"IG_HOLDOUT_74","claim":"The couplet is too small to identify a language securely by itself.","action":"After the 4C channel and morphology audit, use the 74-term corpus as chronological holdout: freeze weights first, then test whether Old Arin, Turkic or contact predictions generalize."}
    ]}
    (out/"next_search.json").write_text(json.dumps(next_search,ensure_ascii=False,indent=2),encoding="utf-8")

    lines=[
        f"# Shile ANRE run — {q['model_version']}","",
        f"Question: {q['research_question']}","",
        "## Dependency collapse"
    ]
    for g,ids in groups.items():
        lines.append(f"- {g}: {', '.join(ids)}")
    lines += ["","## 4C transcription lattice"]
    for r in lattice_rows:
        lines.append(f"- {r['char']}: Shimunek={r['shimunek2015']} | Vovin={r['vovin2016']} | {r['agreement']}")
    lines += ["","## Blind evidence balance (gloss hidden)"]
    for r in blind_matrix:
        lines.append(f"- {r['name']}: {r['blind_evidence_balance']:+d} (support {r['support_count']}, challenge {r['challenge_count']})")
    lines += ["","## Ablation leaders"]
    for aid,s in ablation_summary.items():
        lines.append(f"- {aid}: {', '.join(s['leaders'])} at {s['top_score']:+d}")
    lines += ["","## Legacy seeded-prior order (comparison only)"]
    for r in scores:
        lines.append(f"- {r['name']}: {r['anre_score']:.4f} ({r['status']})")
    lines += ["","## Contradictions"]
    for c in q["contradictions"]:
        lines.append(f"- {c['id']}: {c['claim']} → {c['action']}")
    lines += [
        "","## Interpretation guard",
        "Blind evidence-balance totals are transparent bookkeeping, not probabilities. The strongest current discriminator is morphology; if removing morphology changes the leader, the language identification remains morphology-dependent rather than locked.",
        "A high score never promotes a hypothesis to FACT. Promotion requires independent historical evidence, chronology fit, primary morphology checks and successful holdout tests."
    ]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__=="__main__":
    main()
