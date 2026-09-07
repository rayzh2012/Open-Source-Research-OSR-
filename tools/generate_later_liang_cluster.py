#!/usr/bin/env python3
"""Generate Later Liang cluster fixture and pre-extracted JSONL.

Source: public-domain 《晋书·载记第二十二/第二十九》 passages via
zggdwx.com and ctext.org. No LLM/API calls are needed; the script emits the
pre-extractions that the existing compiler ingests with --pre-extracted-jsonl.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT_FIXTURE = Path("historical-person-graph/fixtures/later_liang_cluster.jsonl")
OUT_PRE = Path("historical-person-graph/fixtures/later_liang_cluster_preextracted.jsonl")


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


# Canonical contexts so the existing resolver merges the same person across records.
C_LV_GUANG = "4世纪前秦将领/后凉建立者"
C_LV_SHAO = "吕光太子/后凉隐王"
C_LV_CUAN = "吕光庶长子/后凉灵帝"
C_LV_HONG = "吕光之子/后凉大司马"
C_LV_LONG = "吕光弟吕宝之子/后凉末主"
C_LV_CHAO = "吕光弟吕宝之子/番禾太守"
C_JQ_LOUCHOU = "后凉尚书"
C_JQ_MENGXUN = "沮渠罗仇族人/北凉奠基者"
C_FU_JIAN = "前秦君主"
C_YAO_XING = "后秦君主"

RECORDS = [
    {
        "id": "LL00",
        "text": "是时麟见金泽县，百兽从之，光以为已瑞，以孝武太元十四年僭即三河王位，置百官自丞郎已下，赦其境内，年号麟嘉。光妻石氏、子绍、弟德世至自仇池，光迎于城东，大飨群臣。遣其子左将军他、武贲中郎将纂讨北虏匹勤于三岩山，大破之。立妻石氏为王妃，子绍为世子。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕光载记·立世子绍与遣子纂",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕光", C_LV_GUANG, "光"),
                p("p2", "吕绍", C_LV_SHAO, "子绍"),
                p("p3", "吕纂", C_LV_CUAN, "纂"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2", "p3"],
                  "吕光僭即三河王位，立子绍为世子，遣子纂讨北虏",
                  "子绍为世子"),
            ],
            "relations": [
                r("p1", "p2", "father_of", "e1", "子绍为世子"),
                r("p1", "p3", "father_of", "e1", "遣其子左将军他、武贲中郎将纂讨北虏"),
            ],
            "slices": [
                s("p1", "FAMILY_SUCCESSION", "吕光即位三河王后立吕绍为世子、以吕纂为将",
                  "e1", "子绍为世子"),
            ],
        },
    },
    {
        "id": "LL01",
        "text": "光疾甚，立其太子绍为天王，自号太上皇帝。以吕纂为太尉，吕弘为司徒。谓绍曰：“吾疾病唯增，恐将不济。三寇窥窬，迭伺国隙。吾终以后，使纂统六军，弘管朝政，汝恭己无为，委重二兄，庶可以济。若内相猜贰，衅起萧墙，则晋、赵之变旦夕至矣。”又谓纂、弘曰：“永业才非拨乱，直以正嫡有常，猥居元首。今外有强寇，人心未宁，汝兄弟缉穆，则贻厥万世。若内自相图，则祸不旋踵。”纂、弘泣曰：“不敢有二心。”光以安帝隆安三年死，时年六十三，在位十年。伪谥懿武皇帝，庙号太祖，墓号高陵。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕光载记·疾甚立太子绍",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕光", C_LV_GUANG, "光"),
                p("p2", "吕绍", C_LV_SHAO, "太子绍"),
                p("p3", "吕纂", C_LV_CUAN, "吕纂"),
                p("p4", "吕弘", C_LV_HONG, "吕弘"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2", "p3", "p4"],
                  "吕光临终立太子绍为天王，以吕纂为太尉、吕弘为司徒",
                  "立其太子绍为天王"),
                e("e2", "other", ["p1"],
                  "吕光卒于隆安三年",
                  "光以安帝隆安三年死"),
            ],
            "relations": [
                r("p1", "p2", "father_of", "e1", "立其太子绍为天王"),
                r("p1", "p3", "appoints", "e1", "以吕纂为太尉"),
                r("p1", "p4", "appoints", "e1", "吕弘为司徒"),
                r("p2", "p1", "succeeds", "e2", "立其太子绍为天王"),
            ],
            "slices": [
                s("p1", "FAMILY_SUCCESSION", "吕光临终安排吕绍嗣位、吕纂统军、吕弘管政",
                  "e1", "使纂统六军，弘管朝政"),
                s("p1", "CRISIS", "吕光警告诸子内斗将致萧墙之祸",
                  "e1", "衅起萧墙，则晋、赵之变旦夕至矣"),
            ],
        },
    },
    {
        "id": "LL02",
        "text": "光死，吕绍秘不发丧，纂排阁入哭，尽哀而出。绍惧为纂所害，以位让之，曰：“兄功高年长，宜承大统，愿兄勿疑。”纂曰：“臣虽年长，陛下国家之冢嫡，不可以私爱而乱大伦。”绍固以让纂，纂不许之。及绍嗣伪位，吕超言于绍曰：“纂统戎积年，威震内外，临丧不哀，步高视远，观其举止乱常，恐成大变，宜早除之，以安社稷。”绍曰：“先帝顾命，音犹在耳，兄弟至亲，岂有此乎！吾弱年而荷大任，方赖二兄以宁家国。纵其图我，我视死如归，终不忍有此意也，卿惧勿过言。”超曰：“纂威名素盛，安忍无亲，今不图之，后必噬脐矣。”绍曰：“吾每念袁尚兄弟，未曾不痛心忘寝食，宁坐而死，岂忍行之。”超曰：“圣人称知机其神，陛下临机不断，臣见大事去矣。”既而纂见绍于湛露堂，超执刀侍绍，目纂请收之，绍弗许。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕纂载记·绍让位与超谏",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕绍", C_LV_SHAO, "吕绍"),
                p("p2", "吕纂", C_LV_CUAN, "纂"),
                p("p3", "吕超", C_LV_CHAO, "吕超"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2", "p3"],
                  "吕绍惧纂让位，吕超谏绍早除纂",
                  "绍惧为纂所害，以位让之"),
                e("e2", "other", ["p1", "p2", "p3"],
                  "吕超执刀请绍收纂，绍不许",
                  "超执刀侍绍，目纂请收之，绍弗许"),
            ],
            "relations": [
                r("p3", "p1", "subordinate_to", "e2", "超执刀侍绍"),
            ],
            "slices": [
                s("p1", "TRUST_BETRAYAL", "吕绍拒纳吕超诛纂之谏",
                  "e1", "纵其图我，我视死如归，终不忍有此意也"),
                s("p3", "CRISIS", "吕超谏吕绍早除吕纂",
                  "e1", "纂统戎积年，威震内外，临丧不哀，步高视远，观其举止乱常，恐成大变，宜早除之"),
            ],
        },
    },
    {
        "id": "LL03",
        "text": "纂于是夜率壮士数百，逾北城，攻广夏门，弘率东苑之众斫洪范门。左卫齐从守融明观，逆问之曰：“谁也？”众曰：“太原公。”从曰：“国有大故，主上新立，太原公行不由道，夜入禁城，将为乱邪？”因抽剑直前，斫纂中额。纂左右擒之，纂曰：“义士也，勿杀。”绍遣武贲中郎将吕开率其禁兵距战于端门，骁骑吕超率卒二千赴之。众素惮纂，悉皆溃散。纂入自青角门，升于谦光殿。绍登紫阁自杀，吕超出奔广武。纂惮弘兵强，劝弘即位。弘曰：“自以绍弟也而承大统，众心不顺，是以违先帝遗敕，惭负黄泉。今复越兄而立，何面目以视息世间！大兄长且贤，威名振于二贼，宜速即大位，以安国家。”纂以隆安四年遂僭即天王位，大赦境内，改元为咸宁，谥绍为隐王。以弘为使持节、侍中、大都督、都督中外诸军事、大司马、车骑大将军、司隶校尉、录尚书事，改封番禾郡公，其余封拜各有差。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕纂载记·纂即位与弘辞位",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕纂", C_LV_CUAN, "纂"),
                p("p2", "吕绍", C_LV_SHAO, "绍"),
                p("p3", "吕弘", C_LV_HONG, "弘"),
                p("p4", "吕超", C_LV_CHAO, "吕超"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2", "p3", "p4"],
                  "吕纂夜攻宫门，吕绍自杀，吕纂即位",
                  "绍登紫阁自杀"),
                e("e2", "other", ["p1", "p3"],
                  "吕弘以弟身份辞位，劝吕纂即位",
                  "大兄长且贤，威名振于二贼，宜速即大位，以安国家"),
            ],
            "relations": [
                r("p1", "p2", "succeeds", "e1", "纂以隆安四年遂僭即天王位"),
                r("p3", "p2", "brother_of", "e2", "自以绍弟也而承大统"),
                r("p3", "p1", "supports", "e2", "宜速即大位，以安国家"),
                r("p1", "p3", "appoints", "e1", "以弘为使持节、侍中、大都督、都督中外诸军事、大司马"),
            ],
            "slices": [
                s("p1", "POWER", "吕纂以政变即位并改元咸宁",
                  "e1", "纂以隆安四年遂僭即天王位，大赦境内，改元为咸宁"),
                s("p2", "CRISIS", "吕绍在纂攻宫中自杀",
                  "e1", "绍登紫阁自杀"),
                s("p3", "FAMILY_SUCCESSION", "吕弘以绍弟身份辞位让纂",
                  "e2", "自以绍弟也而承大统，众心不顺"),
            ],
        },
    },
    {
        "id": "LL04",
        "text": "初，光欲立弘为世子，会闻绍在仇池，乃止，弘由是有憾于绍。吕弘自以功名崇重，恐不为纂所容，纂亦深忌之。弘遂起兵东苑，劫尹文、杨桓以为谋主，请宗燮俱行。燮曰：“老臣受先帝大恩，位为列棘，不能陨身授命，死有余罪，而复从殿下，亲为戎首者，岂天地所容乎！且智不能谋，众不足恃，将焉用之！”弘曰：“君为义士，我为乱臣！”乃率兵攻纂。纂遣其将焦辨击弘，弘众溃，出奔广武。纂纵兵大掠，以东苑妇女赏军，弘之妻子亦为士卒所辱。纂笑谓群臣曰：“今日之战何如？”其侍中房晷对曰：“天祸凉室，衅起戚藩。先帝始崩，隐王幽逼，山陵甫讫，大司马惊疑肆逆，京邑交兵，友于接刃。虽弘自取夷灭，亦由陛下无棠棣之义。宜考已责躬，以谢百姓，而反纵兵大掠，幽辱士女。衅自由弘，百姓何罪！且弘妻，陛下之弟妇也；弘女，陛下之侄女也。奈何使无赖小人辱为婢妾。天地神明，岂忍见此！”遂歔欷悲泣。纂改容谢之，召弘妻及男女于东宫，厚抚之。吕方执弘系狱，驰使告纂，纂遣力士康龙拉杀之。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕纂载记·弘起兵反叛",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕弘", C_LV_HONG, "吕弘"),
                p("p2", "吕纂", C_LV_CUAN, "纂"),
                p("p3", "吕光", C_LV_GUANG, "光"),
                p("p4", "吕绍", C_LV_SHAO, "隐王"),
            ],
            "events": [
                e("e1", "betrayal", ["p1", "p2"],
                  "吕弘起兵东苑攻纂",
                  "弘遂起兵东苑"),
                e("e2", "killing", ["p1", "p2"],
                  "吕纂遣力士康龙拉杀吕弘",
                  "纂遣力士康龙拉杀之"),
                e("e3", "succession", ["p3", "p1"],
                  "吕光曾欲立吕弘为世子",
                  "光欲立弘为世子"),
            ],
            "relations": [
                r("p1", "p2", "rebels_against", "e1", "乃率兵攻纂"),
                r("p2", "p1", "kills", "e2", "纂遣力士康龙拉杀之"),
                r("p3", "p1", "father_of", "e3", "光欲立弘为世子"),
                r("p1", "p2", "brother_of", "e2", "弘妻，陛下之弟妇也"),
            ],
            "slices": [
                s("p1", "TRUST_BETRAYAL", "吕弘自疑而反叛吕纂",
                  "e1", "吕弘自以功名崇重，恐不为纂所容，纂亦深忌之。弘遂起兵东苑"),
                s("p2", "CRISIS", "吕纂平定吕弘反叛后杀之",
                  "e2", "纂遣力士康龙拉杀之"),
            ],
        },
    },
    {
        "id": "LL05",
        "text": "纂番禾太守吕超擅伐鲜卑思盘，思盘遣弟乞珍诉超于纂，纂召超将盘入朝。超至姑臧，大惧，自结于殿中监杜尚，纂见超，怒曰：“卿恃兄弟桓桓，欲欺吾也，要当斩卿，然后天下可定。”超顿首不敢。纂因引超及其诸臣宴于内殿。吕隆屡劝纂酒，已至昏醉，乘步輓车将超等游于内。至琨华堂东閤，车不得过，纂亲将窦川、骆腾倚剑于壁，推车过閤。超取剑击纂，纂下车擒超，超刺纂洞胸，奔于宣德堂。川、腾与超格战，超杀之。纂妻杨氏命禁兵讨超，杜尚约兵舍杖。将军魏益多入，斩纂首以徇曰：“纂违先帝之命，杀害太子，荒耽酒猎，昵近小人，轻害忠良，以百姓为草芥。番禾太守超以骨肉之亲，惧社稷颠覆，已除之矣。上以安宗庙，下为太子报仇。凡我士庶，同兹休庆。”",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕纂载记·吕超刺纂",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕超", C_LV_CHAO, "吕超"),
                p("p2", "吕纂", C_LV_CUAN, "纂"),
                p("p3", "吕隆", C_LV_LONG, "吕隆"),
            ],
            "events": [
                e("e1", "killing", ["p1", "p2"],
                  "吕超刺纂洞胸，魏益多斩纂首",
                  "超刺纂洞胸"),
                e("e2", "other", ["p2", "p3"],
                  "吕隆屡劝吕纂酒，致其昏醉",
                  "吕隆屡劝纂酒"),
            ],
            "relations": [
                r("p1", "p2", "kills", "e1", "超刺纂洞胸"),
                r("p3", "p1", "supports", "e2", "吕隆屡劝纂酒", "INFERENCE"),
            ],
            "slices": [
                s("p1", "TRUST_BETRAYAL", "吕超宴中刺杀吕纂",
                  "e1", "超取剑击纂，纂下车擒超，超刺纂洞胸"),
                s("p3", "CRISIS", "吕隆参与灌醉吕纂以行刺",
                  "e2", "吕隆屡劝纂酒"),
            ],
        },
    },
    {
        "id": "LL06",
        "text": "隆字永基，光弟宝之子也，美姿貌，善骑射。光末拜北部护军，稍历显位，有声称。超既杀纂，让位于隆，隆有难色。超曰：“今犹乘龙上天，岂可中下！”隆以安帝元兴元年遂僭即天王位。超先于番禾得小鼎，以为神瑞，大赦，改元为神鼎。追尊父宝为文皇帝，母卫氏为皇太后，妻杨氏为皇后，以弟超有佐命之勋，拜使持节、侍中、都督中外诸军事、辅国大将军、司隶校尉、录尚书事，封安定公。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕隆载记·隆即位",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕隆", C_LV_LONG, "隆"),
                p("p2", "吕超", C_LV_CHAO, "超"),
                p("p3", "吕纂", C_LV_CUAN, "纂"),
                p("p4", "吕光", C_LV_GUANG, "光"),
            ],
            "events": [
                e("e1", "succession", ["p1", "p2", "p3"],
                  "吕超让位与吕隆，吕隆即位",
                  "隆以安帝元兴元年遂僭即天王位"),
                e("e2", "appointment", ["p1", "p2"],
                  "吕隆以吕超有佐命之功，授重职封安定公",
                  "以弟超有佐命之勋，拜使持节、侍中、都督中外诸军事、辅国大将军、司隶校尉、录尚书事，封安定公"),
            ],
            "relations": [
                r("p1", "p3", "succeeds", "e1", "隆以安帝元兴元年遂僭即天王位"),
                r("p2", "p1", "supports", "e2", "以弟超有佐命之勋"),
                r("p1", "p2", "brother_of", "e2", "以弟超有佐命之勋"),
                r("p4", "p1", "uncle_of", "e1", "光弟宝之子也"),
            ],
            "slices": [
                s("p1", "FAMILY_SUCCESSION", "吕隆在吕超支持下即位",
                  "e1", "超既杀纂，让位于隆"),
                s("p2", "POWER", "吕超因佐命之功获重权",
                  "e2", "以弟超有佐命之勋，拜使持节、侍中、都督中外诸军事、辅国大将军、司隶校尉、录尚书事，封安定公"),
            ],
        },
    },
    {
        "id": "LL07",
        "text": "隆多杀豪望，以立威名，内外嚣然，人不自固。魏安人焦朗遣使说姚兴将姚硕德曰：“吕氏因秦之乱，制命此州。自武皇弃世，诸子兢寻干戈，德刑不恤，残暴是先，饥馑流亡，死者太半，唯泣诉昊天，而精诚无感。伏惟明公道迈前贤，任尊分陕，宜兼弱攻昧，经略此方，救生灵之沈溺，布徽政于玉门。篡夺之际，为功不难。”遣妻子为质。硕德遂率众至姑臧。其部将姚国方言于硕德曰：“今悬师三千，后无继援，师之难也。宜曜劲锋，示其威武。彼以我远来，必决死距战，可一举而平。”硕德从之。吕超出战，大败，遁还。隆收集离散，婴城固守。时荧惑犯帝坐，有群雀斗于太庙，死者数万。东人多谋外叛，将军魏益多又唱动群心，乃谋杀隆、超，事发，诛之，死者三百余家。于是群臣表求与姚兴通好，隆弗许。吕超谏曰：“通塞有时，艰泰相袭，孙权屈身于魏，谯周劝主迎降，岂非大丈夫哉？势屈故也。天锡承七世之资，树恩百载，武旅十万，谋臣盈朝，秦师临境，识者导以见机，而愎谏自专，社稷为墟。前鉴不远，我之元龟也。何惜尺书单使，不以危易安！且令卑辞以退敌，然后内修德政，废兴由人，未损大略。”隆曰：“吾虽常人，属当家国之重，不能嗣守成基，保安社稷，以太祖之业委之于人，何面目见先帝于地下！”超曰：“应龙以屈伸为灵，大人以知机为美。今连兵积岁，资储内尽，强寇外逼，百姓嗷然无糊口之寄，假使张、陈、韩、白，亦无如之何！陛下宜思权变大纲，割区区常虑。苟卜世有期，不在和好，若天命去矣，宗族可全。”隆从之，乃请降。硕德表隆为使持节、镇西大将军、凉州刺史、建康公。于是遣母弟爱子文武旧臣慕容筑、杨颖、史难、阎松等五十余家质于长安，硕德乃还。姚兴谋臣皆曰：“隆藉伯父余资，制命河外。今虽饥窘，尚能自支。若将来丰赡，终非国有。凉州险绝，世难先违，道清后顺，不如因其饥弊而取之。”兴乃遣使来观虚实。沮渠蒙逊又伐隆，隆击败之，蒙逊请和结盟，留谷万余斛以振饥人。姑臧谷价踊贵，斗直钱五千文，人相食，饥死者十余万口。城门尽闭，樵采路绝，百姓请出城乞为夷虏奴婢者日有数百。隆惧沮动人情，尽坑之，于是积尸盈于卫路。秃发傉檀及蒙逊频来伐之，隆以二寇之逼也，遣超率骑二百，多赍珍宝，请迎于姚兴。兴乃遣其将齐难等步骑四万迎之。难至姑臧，隆素车白马迎于道旁。使胤告光庙曰：“陛下往运神略，开建西夏，德被苍生，威振遐裔。枝嗣不臧，迭相篡弑。二虏交逼，将归东京，谨与陛下奉诀于此。”歔欷恸泣，酸感兴军。隆率户一万，随难东迁，至长安，兴以隆为散骑常侍，公如故；超为安定太守；文武三十余人皆擢叙之。其后隆坐与子弼谋反，为兴所诛。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕隆载记·隆降姚兴",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕隆", C_LV_LONG, "吕隆"),
                p("p2", "吕超", C_LV_CHAO, "吕超"),
                p("p3", "姚兴", C_YAO_XING, "姚兴"),
                p("p4", "沮渠蒙逊", C_JQ_MENGXUN, "蒙逊"),
            ],
            "events": [
                e("e1", "war", ["p3", "p1"],
                  "姚兴遣姚硕德攻吕隆于姑臧",
                  "硕德遂率众至姑臧"),
                e("e2", "other", ["p1", "p3"],
                  "吕隆向姚硕德请降",
                  "隆从之，乃请降"),
                e("e3", "appointment", ["p3", "p1"],
                  "姚兴以吕隆为散骑常侍",
                  "兴以隆为散骑常侍，公如故"),
                e("e4", "other", ["p4", "p1"],
                  "沮渠蒙逊伐吕隆，隆击败之，蒙逊请和",
                  "沮渠蒙逊又伐隆，隆击败之，蒙逊请和结盟"),
                e("e5", "other", ["p1", "p2", "p3"],
                  "吕隆遣吕超迎请于姚兴",
                  "遣超率骑二百，多赍珍宝，请迎于姚兴"),
                e("e6", "killing", ["p3", "p1"],
                  "吕隆后与子弼谋反，为姚兴所诛",
                  "其后隆坐与子弼谋反，为兴所诛"),
            ],
            "relations": [
                r("p3", "p1", "enemy_of", "e1", "硕德遂率众至姑臧"),
                r("p3", "p1", "appoints", "e3", "兴以隆为散骑常侍，公如故"),
                r("p4", "p1", "enemy_of", "e4", "沮渠蒙逊又伐隆"),
                r("p1", "p3", "sends_envoy_to", "e5", "遣超率骑二百，多赍珍宝，请迎于姚兴"),
                r("p3", "p1", "kills", "e6", "其后隆坐与子弼谋反，为兴所诛"),
            ],
            "slices": [
                s("p1", "CRISIS", "吕隆困于外寇内叛，最终向姚兴请降",
                  "e2", "隆从之，乃请降"),
                s("p1", "FAILURE_BLINDSPOT", "吕隆多杀豪望以立威",
                  "e1", "隆多杀豪望，以立威名"),
                s("p3", "POWER", "姚兴遣将攻隆并受降后授官",
                  "e3", "兴以隆为散骑常侍，公如故"),
                s("p4", "DYAD_INTERACTION", "沮渠蒙逊趁吕隆困境伐隆",
                  "e4", "沮渠蒙逊又伐隆"),
            ],
        },
    },
    {
        "id": "LL09",
        "text": "坚既平山东，士马强盛，遂有图西域之志，乃授光使持节、都督西讨诸军事，率将军姜飞、彭晃、杜进、康盛等总兵七万，铁骑五千，以讨西域，以陇西董方、冯翊郭抱、武威贾虔、弘农杨颖为四府佐将。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕光载记·苻坚授光西讨",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "苻坚", C_FU_JIAN, "苻坚"),
                p("p2", "吕光", C_LV_GUANG, "光"),
            ],
            "events": [
                e("e1", "appointment", ["p1", "p2"],
                  "苻坚授吕光使持节、都督西讨诸军事",
                  "乃授光使持节、都督西讨诸军事"),
            ],
            "relations": [
                r("p1", "p2", "appoints", "e1", "乃授光使持节、都督西讨诸军事"),
                r("p2", "p1", "subordinate_to", "e1", "乃授光使持节、都督西讨诸军事"),
            ],
            "slices": [
                s("p1", "POWER", "苻坚授吕光西征大军节度",
                  "e1", "乃授光使持节、都督西讨诸军事"),
            ],
        },
    },
    {
        "id": "LL10",
        "text": "苻重之镇洛阳，以光为长史。及重谋反，苻坚闻之，曰：“吕光忠孝方正，必不同也。”驰使命光槛重送之。寻入为太子右率，甚见敬重。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕光载记·苻坚评光忠孝",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "苻坚", C_FU_JIAN, "苻坚"),
                p("p2", "吕光", C_LV_GUANG, "吕光"),
            ],
            "events": [
                e("e1", "speech", ["p1", "p2"],
                  "苻坚评价吕光忠孝方正，认为其不附谋反",
                  "吕光忠孝方正，必不同也"),
            ],
            "relations": [
                r("p1", "p2", "supports", "e1", "吕光忠孝方正，必不同也"),
            ],
            "slices": [
                s("p2", "RELATION", "苻坚在谋反案中信任吕光",
                  "e1", "吕光忠孝方正，必不同也"),
            ],
        },
    },
    {
        "id": "LL11",
        "text": "光荒耄信谗，杀尚书沮渠罗仇、三河太守沮渠麹粥。罗仇弟子蒙逊叛光，杀中田护军马邃，攻陷临松郡，屯兵金山，大为百姓之患。",
        "source_kind": "primary-public-domain",
        "source_title": "晋书",
        "source_locator": "载记第二十二·吕光载记·光杀罗仇蒙逊叛",
        "quoted_source": "https://www.zggdwx.com/jinshu/123.html",
        "evidence_tier": "A",
        "extraction": {
            "persons": [
                p("p1", "吕光", C_LV_GUANG, "光"),
                p("p2", "沮渠罗仇", C_JQ_LOUCHOU, "沮渠罗仇"),
                p("p3", "沮渠蒙逊", C_JQ_MENGXUN, "蒙逊"),
            ],
            "events": [
                e("e1", "killing", ["p1", "p2"],
                  "吕光杀尚书沮渠罗仇与三河太守沮渠麹粥",
                  "杀尚书沮渠罗仇、三河太守沮渠麹粥"),
                e("e2", "betrayal", ["p3", "p1"],
                  "沮渠蒙逊因罗仇之死叛离吕光",
                  "罗仇弟子蒙逊叛光"),
            ],
            "relations": [
                r("p1", "p2", "kills", "e1", "杀尚书沮渠罗仇、三河太守沮渠麹粥"),
                r("p3", "p1", "rebels_against", "e2", "罗仇弟子蒙逊叛光"),
            ],
            "slices": [
                s("p1", "TRUST_BETRAYAL", "吕光晚年信谗诛杀沮渠氏官员",
                  "e1", "光荒耄信谗，杀尚书沮渠罗仇、三河太守沮渠麹粥"),
                s("p3", "CRISIS", "沮渠蒙逊因罗仇之死聚众叛光",
                  "e2", "罗仇弟子蒙逊叛光"),
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
