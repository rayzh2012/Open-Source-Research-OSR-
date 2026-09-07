#!/usr/bin/env python3
"""Generate Yao Hong -> Liu Yu bridge fixture and pre-extracted JSONL.

Source: public-domain 《晋书·载记第十九·姚泓》 and 《宋书·本纪第二·武帝中》
passages via zggdwx.com and guwendao.net. No LLM/API calls are needed; the script
emits the pre-extractions that the existing compiler ingests with
--pre-extracted-jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT_FIXTURE = Path("historical-person-graph/fixtures/yao_hong_liu_yu_bridge.jsonl")
OUT_PRE = Path("historical-person-graph/fixtures/yao_hong_liu_yu_bridge_preextracted.jsonl")


def p(local_id: str, name: str, context: str, evidence: str, aliases=None):
    return {
        "local_id": local_id,
        "name": name,
        "aliases": aliases or [],
        "context": context,
        "certainty": "FACT",
        "evidence": evidence,
    }


def e(local_id: str, event_type: str, participants: list[str], summary: str,
      evidence: str, certainty: str = "FACT"):
    return {
        "local_id": local_id,
        "date_text": "",
        "event_type": event_type,
        "participants": participants,
        "summary": summary,
        "certainty": certainty,
        "evidence": evidence,
    }


def r(source: str, target: str, relation_type: str, event: str,
      evidence: str, certainty: str = "FACT"):
    return {
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "event": event,
        "start_text": "",
        "end_text": "",
        "certainty": certainty,
        "evidence": evidence,
    }


def s(person: str, slice_type: str, claim: str, event: str,
      evidence: str, certainty: str = "FACT"):
    return {
        "person": person,
        "slice_type": slice_type,
        "claim": claim,
        "event": event,
        "certainty": certainty,
        "evidence": evidence,
    }


# Canonical contexts. 姚兴 must match the v1 graph exactly so the compiler merges.
C_YAO_XING = "后秦君主"
C_YAO_HONG = "后秦末代君主/姚兴长子"
C_LIU_YU = "东晋太尉/宋武帝"
C_WANG_ZHEN_E = "龙骧将军/刘裕前锋"
C_TAN_DAO_JI = "冠军将军/刘裕前锋"

RECORDS = [
    {
        "id": "YH01",
        "text": "姚泓，字元子，兴之长子也。孝友宽和，而无经世之用，又多疾病，兴将以为嗣而疑焉。久之，乃立为太子。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十九·姚泓载记·立太子",
        "quoted_source": "https://www.zggdwx.com/jinshu/120.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "姚泓", C_YAO_HONG, "姚泓"),
                p("p2", "姚兴", C_YAO_XING, "兴"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2"],
                  "姚兴立长子姚泓为太子",
                  "乃立为太子"),
            ],
            "relations": [
                r("p2", "p1", "father_of", "e1", "兴之长子也"),
            ],
            "slices": [
                s("p1", "FAMILY_SUCCESSION", "姚泓为姚兴长子，被立为太子",
                  "e1", "久之，乃立为太子"),
            ],
        },
    },
    {
        "id": "YH02",
        "text": "兴既死，秘不发丧。南阳公姚愔及大将军尹元等谋为乱，泓皆诛之。命其齐公姚恢杀安定太守吕超，恢久乃诛之。泓疑恢有阴谋，恢自是怀贰，阴聚兵甲焉。泓发丧，以义熙十二年僭即帝位，大赦殊死已下，改元永和，庐于谘议堂。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十九·姚泓载记·即位",
        "quoted_source": "https://www.zggdwx.com/jinshu/120.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "姚泓", C_YAO_HONG, "泓"),
                p("p2", "姚兴", C_YAO_XING, "兴"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2"],
                  "姚兴死后，姚泓发丧即位",
                  "以义熙十二年僭即帝位"),
            ],
            "relations": [
                r("p1", "p2", "succeeds", "e1", "以义熙十二年僭即帝位"),
            ],
            "slices": [
                s("p1", "FAMILY_SUCCESSION", "姚兴死后姚泓即位",
                  "e1", "泓发丧，以义熙十二年僭即帝位"),
            ],
        },
    },
    {
        "id": "YH03",
        "text": "寻而晋太尉刘裕总大军伐泓，次于彭城，遣冠军将军檀道济、龙骧将军王镇恶入自淮、肥，攻漆丘、项城，将军沈林子自汴入河，攻仓垣。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十九·姚泓载记·刘裕伐泓",
        "quoted_source": "https://www.zggdwx.com/jinshu/120.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "刘裕", C_LIU_YU, "刘裕"),
                p("p2", "姚泓", C_YAO_HONG, "泓"),
                p("p3", "檀道济", C_TAN_DAO_JI, "檀道济"),
                p("p4", "王镇恶", C_WANG_ZHEN_E, "王镇恶"),
            ],
            "events": [
                e("e1", "war", ["p1", "p2"],
                  "晋太尉刘裕总大军伐后秦姚泓",
                  "晋太尉刘裕总大军伐泓"),
                e("e2", "appointment", ["p1", "p3", "p4"],
                  "刘裕遣檀道济、王镇恶等为将攻秦",
                  "遣冠军将军檀道济、龙骧将军王镇恶"),
            ],
            "relations": [
                r("p1", "p2", "enemy_of", "e1", "晋太尉刘裕总大军伐泓"),
                r("p1", "p3", "commands", "e2", "遣冠军将军檀道济"),
                r("p1", "p4", "commands", "e2", "龙骧将军王镇恶"),
            ],
            "slices": [
                s("p1", "WAR_COMMAND", "刘裕总大军北伐姚泓",
                  "e1", "晋太尉刘裕总大军伐泓"),
                s("p3", "POWER", "檀道济受刘裕命攻秦",
                  "e2", "遣冠军将军檀道济"),
                s("p4", "POWER", "王镇恶受刘裕命攻秦",
                  "e2", "龙骧将军王镇恶"),
            ],
        },
    },
    {
        "id": "YH04",
        "text": "八月，扶风太守沈田子大破姚泓于蓝田。王镇恶克长安，生擒泓。九月，公至长安。长安丰稔，帑藏盈积。公先收其彝器、浑仪、土圭之属，献于京师；其余珍宝珠玉，以班赐将帅。执送姚泓，斩于建康市。",
        "source_kind": "primary-public-domain",
        "source_title": "宋书",
        "source_locator": "本纪第二·武帝中·义熙十三年",
        "quoted_source": "https://m.guwendao.net/guwen/bookv_4ff2657fa5a0.aspx",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "王镇恶", C_WANG_ZHEN_E, "王镇恶"),
                p("p2", "姚泓", C_YAO_HONG, "姚泓"),
                p("p3", "刘裕", C_LIU_YU, "公"),
            ],
            "events": [
                e("e1", "war", ["p1", "p2"],
                  "王镇恶克长安，生擒姚泓",
                  "王镇恶克长安，生擒泓"),
                e("e2", "killing", ["p3", "p2"],
                  "刘裕执送姚泓，斩于建康市",
                  "执送姚泓，斩于建康市"),
            ],
            "relations": [
                r("p2", "p1", "captured_by", "e1", "王镇恶克长安，生擒泓"),
                r("p2", "p3", "executed_by", "e2", "执送姚泓，斩于建康市"),
            ],
            "slices": [
                s("p1", "WAR_COMMAND", "王镇恶克长安并生擒姚泓",
                  "e1", "王镇恶克长安，生擒泓"),
                s("p2", "CRISIS", "姚泓被王镇恶生擒，后被刘裕处决",
                  "e2", "执送姚泓，斩于建康市"),
            ],
        },
    },
    {
        "id": "YH05",
        "text": "泓计无所出，谋欲降于裕。其子佛念，年十一，谓泓曰：“晋人将逞其欲，终必不全，愿自裁决。”泓怃然不答。佛念遂登宫墙自投而死。泓将妻子诣垒门而降。赞率宗室子弟百余人亦降于裕，裕尽杀之，余宗迁于江南。送泓于建康市斩之，时年三十，在位二年。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十九·姚泓载记·投降被斩",
        "quoted_source": "https://www.zggdwx.com/jinshu/120.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "姚泓", C_YAO_HONG, "泓"),
                p("p2", "刘裕", C_LIU_YU, "裕"),
            ],
            "events": [
                e("e1", "other", ["p1", "p2"],
                  "姚泓计无所出，谋欲降于刘裕",
                  "谋欲降于裕"),
                e("e2", "killing", ["p2", "p1"],
                  "姚泓被送建康市斩首",
                  "送泓于建康市斩之"),
            ],
            "relations": [
                # e2 is recorded as an event/slice; the executed_by edge is already
                # grounded in YH04 from 宋书. Keeping only one edge avoids redundancy.
            ],
            "slices": [
                s("p1", "CRISIS", "姚泓穷途谋降，终被送建康斩首",
                  "e2", "送泓于建康市斩之"),
            ],
        },
    },
]


def main() -> int:
    OUT_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    OUT_PRE.parent.mkdir(parents=True, exist_ok=True)
    with OUT_FIXTURE.open("wt", encoding="utf-8") as ffix, OUT_PRE.open("wt", encoding="utf-8") as fpre:
        for rec in RECORDS:
            fixture = {k: v for k, v in rec.items() if k != "extraction"}
            ffix.write(json.dumps(fixture, ensure_ascii=False) + "\n")
            fpre.write(json.dumps({
                "id": rec["id"],
                "extraction": rec["extraction"],
            }, ensure_ascii=False) + "\n")
    print(json.dumps({
        "status": "PASS",
        "fixture": str(OUT_FIXTURE),
        "pre_extracted": str(OUT_PRE),
        "records": len(RECORDS),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
