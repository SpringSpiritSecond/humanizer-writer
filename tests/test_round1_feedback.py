"""第一轮盲审反馈落地的几项通用改动：话语类指标、brief 风格指令提示。"""
import json
from pathlib import Path

from detect.stages import g3
from pipeline.gates.brief import style_directives

ROOT = Path(__file__).resolve().parents[1]
P_DLG = json.loads((ROOT / "profiles/台词.json").read_text(encoding="utf-8"))
P_VO = json.loads((ROOT / "profiles/口播.json").read_text(encoding="utf-8"))


def m(text, line="台词", profile=P_DLG):
    return g3({"line": line, "brief": {}, "profile": profile, "text": text, "round": 0, "history": [], "config": {}})["metrics"]


BARKING = "H01：主炮满了！\nH02：快！\nH01：来！\nH02：一起！\n梯梯：哔哔！\nH01：出发！"
TALKING = ("H01：主炮已经满了，我现在就想打它。\nH02：先别动，星图还是黑的，你打出去也找不到它的核心。\n"
           "H01：那要等多久？它都快贴上来了。\n梯梯：哔——\nH02：梯梯说它可以试试，你让一下导航台。")


def test_barking_dialogue_scores_high():
    x = m(BARKING)
    assert x["utterances"] == 5                      # 纯拟声“哔哔！”不算
    assert x["exclaim_ratio"] == 1.0
    assert x["fragment_ratio"] >= 0.6
    assert x["bare_imperative_ratio"] >= 0.6


def test_talking_dialogue_scores_low():
    x = m(TALKING)
    assert x["exclaim_ratio"] == 0 and x["fragment_ratio"] == 0 and x["bare_imperative_ratio"] == 0


def test_imperative_with_reason_is_not_bare():
    x = m("快走，不然门要关了！\n来，因为要先站稳！\n出发！", line="口播", profile=P_VO)
    assert x["bare_imperative_ratio"] == round(1 / 3, 3)


def test_too_few_sentences_gives_none():
    assert m("H01：好！")["exclaim_ratio"] is None


def test_style_directives_found_and_deduped():
    brief = {"id": "x", "line": "台词", "source": {"note": "要短"}, "context": "台词要短，制造紧张感",
             "speaker": "语气平实，不煽情"}
    found = {h["excerpt"]: h["field"] for h in style_directives(brief)}
    assert found == {"要短": "context", "制造紧张": "context", "紧张感": "context",
                     "语气平实": "speaker", "不煽情": "speaker"}
    assert all(h["severity"] == "warn" for h in style_directives(brief))


def test_situation_brief_has_no_style_directives():
    brief = {"id": "x", "line": "科普", "speaker": "康复师，一位家长刚问孩子为什么总撞东西，当面回答他"}
    assert style_directives(brief) == []
