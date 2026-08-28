#!/usr/bin/env python3
"""Generate Fu Jian -> Yao Chang -> Yao Xing -> Yao Hong -> Liu Yu chain fixture.

Source: public-domain 《晋书·载记第十六·姚苌》、 《晋书·载记第十五·苻坚载记下》、
《晋书·载记第十七·姚兴载记》 passages via zggdwx.com. No LLM/API calls are needed.
The script emits pre-extractions that the existing compiler ingests with
--pre-extracted-jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT_FIXTURE = Path("historical-person-graph/fixtures/fuqin_yaochang_yaoxing_bridge.jsonl")
OUT_PRE = Path("historical-person-graph/fixtures/fuqin_yaochang_yaoxing_bridge_preextracted.jsonl")


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


# Canonical contexts. 姚兴 and 苻坚 must match the v2 graph exactly so the compiler merges.
C_FU_JIAN = "前秦君主"
C_YAO_CHANG = "后秦武昭皇帝/姚兴之父"
C_YAO_XING = "后秦君主"
C_WU_ZHONG = "后秦将军/姚苌部将"

RECORDS = [
    {
        "id": "FC01",
        "text": "苻坚以苌为扬武将军。历左卫将军，陇东、汲郡、河东、武都、武威、巴西、扶风太守，宁、幽、兗三州刺史，复为扬武将军，步兵校尉，封益都侯。为坚将，累有大功。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十六·姚苌载记·为坚将",
        "quoted_source": "https://www.zggdwx.com/jinshu/117.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "姚苌", C_YAO_CHANG, "苌"),
                p("p2", "苻坚", C_FU_JIAN, "坚"),
            ],
            "events": [
                e("e1", "appointment", ["p1", "p2"],
                  "苻坚以姚苌为扬武将军等职，累有大功",
                  "苻坚以苌为扬武将军"),
            ],
            "relations": [
                r("p2", "p1", "appoints", "e1", "苻坚以苌为扬武将军"),
                r("p1", "p2", "subordinate_to", "e1", "为坚将，累有大功"),
            ],
            "slices": [
                s("p1", "POWER", "姚苌为苻坚将，历任要职",
                  "e1", "苻坚以苌为扬武将军"),
            ],
        },
    },
    {
        "id": "FC02",
        "text": "坚既败于淮南，归长安，慕容泓起兵叛坚。坚遣子叡讨之，以苌为司马。为泓所败，叡死之。苌遣龙骧长史赵都诣坚谢罪，坚怒，杀之。苌惧，奔于渭北，遂如马牧。西州豪族尹详、赵曜、王钦卢、王钦卢、牛双、狄广、张乾等率五万余家，咸推苌为盟主。苌将距之，天水尹纬说苌曰：\"今百六之数既臻，秦亡之兆已见，以将军威灵命世，必能匡济时艰，故豪杰驱驰，咸同推仰。明公宜降心从议，以副群望，不可坐观沈溺而不拯救之。\"苌乃从纬谋，以太元九年自称大将军、大单于、万年秦王，大赦境内，年号白雀，称制行事。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十六·姚苌载记·叛坚称秦王",
        "quoted_source": "https://www.zggdwx.com/jinshu/117.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "姚苌", C_YAO_CHANG, "苌"),
                p("p2", "苻坚", C_FU_JIAN, "坚"),
            ],
            "events": [
                e("e1", "betrayal", ["p1", "p2"],
                  "姚苌因惧诛，叛离苻坚，自称万年秦王",
                  "苌乃从纬谋，以太元九年自称大将军、大单于、万年秦王"),
            ],
            "relations": [
                r("p1", "p2", "rebels_against", "e1", "自称大将军、大单于、万年秦王"),
                r("p1", "p2", "enemy_of", "e1", "苌惧，奔于渭北"),
            ],
            "slices": [
                s("p1", "TRUST_BETRAYAL", "姚苌因苻坚杀赵都而惧，叛秦自立",
                  "e1", "苌遣龙骧长史赵都诣坚谢罪，坚怒，杀之。苌惧，奔于渭北"),
            ],
        },
    },
    {
        "id": "FC03",
        "text": "坚至五将山，姚苌遣将军吴忠围之。坚众奔散，独侍御十数人而已。神色自若，坐而待之，召宰人进食。俄而忠至，执坚以归新平，幽之于别室。苌求传国玺于坚曰：\"苌次膺符历，可以为惠。\"坚瞋目叱之曰：\"小羌乃敢干逼天子，岂以传国玺授汝羌也，图纬符命，何所依据？五胡次序，无汝羌名。违天不祥，其能久乎！玺已送晋，不可得也。\"苌又遣尹纬说坚，求为尧、舜禅代之事。坚责纬曰：\"禅代者，圣贤之事。姚苌叛贼，奈何拟之古人！\"坚既不许苌以禅代，骂而求死，苌乃缢坚于新平佛寺中，时年四十八。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十五·苻坚载记下·姚苌缢坚",
        "quoted_source": "https://www.zggdwx.com/jinshu/115.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "姚苌", C_YAO_CHANG, "苌"),
                p("p2", "苻坚", C_FU_JIAN, "坚"),
                p("p3", "吴忠", C_WU_ZHONG, "吴忠"),
            ],
            "events": [
                e("e1", "war", ["p2", "p3"],
                  "吴忠奉姚苌命围五将山，执苻坚归新平",
                  "俄而忠至，执坚以归新平"),
                e("e2", "killing", ["p1", "p2"],
                  "姚苌缢杀苻坚于新平佛寺",
                  "苌乃缢坚于新平佛寺中"),
            ],
            "relations": [
                r("p1", "p3", "commands", "e1", "姚苌遣将军吴忠围之"),
                r("p2", "p3", "captured_by", "e1", "俄而忠至，执坚以归新平"),
                r("p2", "p1", "executed_by", "e2", "苌乃缢坚于新平佛寺中"),
            ],
            "slices": [
                s("p2", "CRISIS", "苻坚被吴忠执送姚苌，终遭缢杀",
                  "e2", "苌乃缢坚于新平佛寺中"),
                s("p1", "CRISIS", "姚苌遣将围捕并缢杀苻坚",
                  "e2", "苌乃缢坚于新平佛寺中"),
            ],
        },
    },
    {
        "id": "FC04",
        "text": "姚兴，字子略，苌之长子也。苻坚时为太子舍人。苌之在马牧，兴自长安冒难奔苌，苌立为皇太子。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十七·姚兴载记·兴奔苌",
        "quoted_source": "https://www.zggdwx.com/jinshu/117.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "姚苌", C_YAO_CHANG, "苌"),
                p("p2", "姚兴", C_YAO_XING, "兴"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2"],
                  "姚苌立长子姚兴为皇太子",
                  "苌立为皇太子"),
            ],
            "relations": [
                r("p1", "p2", "father_of", "e1", "苌之长子也"),
            ],
            "slices": [
                s("p2", "FAMILY_SUCCESSION", "姚兴为姚苌长子，被立为皇太子",
                  "e1", "苌之长子也"),
                s("p1", "FAMILY_SUCCESSION", "姚苌立长子姚兴为皇太子",
                  "e1", "苌立为皇太子"),
            ],
        },
    },
    {
        "id": "FC05",
        "text": "苌死，兴秘不发丧，以其叔父绪镇安定，硕德镇阴密，弟崇守长安。硕德将佐言于硕德曰：\"公威名宿重，部曲最强，今丧代之际，朝廷必相猜忌，非永安之道也。宜奔秦州，观望事势。\"硕德曰：\"太子志度宽明，必无疑阻。今苻登未灭而自寻干戈，所谓追二袁之踪，授首与人。吾死而已，终不若斯。\"及至，兴优礼而遣之。兴自称大将军，以尹纬为长史，狄伯支为司马，率众伐苻登。咸阳太守刘忌奴据避世堡以叛，兴袭忌奴，擒之。苻登自六陌向废桥，始平太守姚详据马嵬堡以距登。登众甚盛，兴虑详不能遏，乃自将精骑以迫登，遣尹纬领步卒赴详。纬用详计，据废桥以抗登。登因急攻纬，纬将出战，兴驰遣狄伯支谓纬曰：\"兵法不战而制人者，盖为此也。苻登穷寇，宜持重，不可轻战。\"纬曰：\"先帝登遐，人情扰惧，今不因思奋之力，枭殄逆竖，大事去矣。纬敢以死争。\"遂与登战，大破之，登众渴死者十二三，其夜大溃，登奔雍。兴乃发丧行服。太元十九年，僭即帝位于槐里，大赦境内，改元曰皇初，遂如安定。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第十七·姚兴载记·兴即位",
        "quoted_source": "https://www.zggdwx.com/jinshu/118.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "姚兴", C_YAO_XING, "兴"),
                p("p2", "姚苌", C_YAO_CHANG, "苌"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2"],
                  "姚苌死后姚兴秘不发丧，后即位称帝",
                  "太元十九年，僭即帝位"),
            ],
            "relations": [
                r("p1", "p2", "succeeds", "e1", "太元十九年，僭即帝位"),
            ],
            "slices": [
                s("p1", "FAMILY_SUCCESSION", "姚苌死后姚兴即位称帝",
                  "e1", "兴乃发丧行服。太元十九年，僭即帝位"),
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
