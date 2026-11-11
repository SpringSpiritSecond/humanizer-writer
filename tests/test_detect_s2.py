"""S2 规则检测。样本都是自写示例，见 detect/samples/。"""
import copy
import importlib
import json
from pathlib import Path

import pytest

from detect import stages
from detect.text import load_rules

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {line: json.loads((ROOT / "profiles" / f"{line}.json").read_text(encoding="utf-8"))
            for line in ("台词", "口播")}
SAMPLES = {line: json.loads((ROOT / "detect" / "samples" / f"{line}.json").read_text(encoding="utf-8"))
           for line in ("台词", "口播")}
S2_RULES = set(load_rules()["s2"])


def run(text, line="口播", profile=None, brief=None):
    return stages.s2({"line": line, "text": text, "profile": profile if profile is not None else {},
                      "brief": brief or {}, "round": 0, "history": [], "config": {}})


def rules_of(result):
    return [h["rule"] for h in result["hits"]]


# --- 约定 ------------------------------------------------------------------
def test_importable_by_dotted_path():
    mod, fn = "detect.stages:s2".split(":")
    assert getattr(importlib.import_module(mod), fn) is stages.s2


def test_result_shape_follows_contract():
    text = "这不是结束，而是开始。"
    r = run(text)
    assert r["stage"] == "S2" and r["kind"] == "report"
    assert r["verdict"] == "pass" and r["route_to"] is None
    (h,) = r["hits"]
    assert set(h) == {"rule", "span", "excerpt", "severity", "message"}
    s, e = h["span"]
    assert text[s:e] == h["excerpt"] and h["excerpt"].startswith("不是")
    assert h["severity"] in ("block", "warn", "hint")


def test_rule_ids_match_design_doc_table():
    doc = (ROOT / "docs" / "工作流编排.md").read_text(encoding="utf-8")
    flagged = {"not_x_but_y", "de_stacking", "jinxing_verb", "bei_stack", "four_char_parallel",
               "cliche_opening", "cliche_ending", "colon_conclusion", "dash", "rhetorical_question",
               "triple_parallel", "punchline_ending"}
    assert S2_RULES == flagged
    for rid in flagged:
        assert f"`{rid}`" in doc
    tiers = {rid: spec["tier"] for rid, spec in load_rules()["s2"].items()}
    assert {r for r, t in tiers.items() if t == "paragraph"} == {
        "de_stacking", "bei_stack", "four_char_parallel", "dash", "rhetorical_question"}


def test_empty_text():
    r = run("")
    assert r["hits"] == [] and r["verdict"] == "pass"


# --- 每条规则：命中 / 不命中 --------------------------------------------------
CASES = {
    "not_x_but_y": (["这不是结束，而是开始。", "与其等着，不如现在就走。", "它不仅是一台机器，更是一个伙伴。"],
                    ["不是我，是他。", "是不是而是的问题我也不懂。"]),
    "jinxing_verb": (["我们对方案进行调整。", "双方进行了一次沟通。"],
                     ["比赛进行到第三局。", "正在进行的项目有三个。", "婚礼进行曲响了。"]),
    "cliche_opening": (["随着互联网的普及，购物越来越方便。", "在当今社会，大家都很忙。", "众所周知，夏天很热。"],
                       ["他随着人群往前走，手里攥着票。", "我知道。随着互联网的普及，购物方便了。"]),
    "cliche_ending": (["价格很实在。总之，值得一试。", "就聊到这。让我们一起期待吧。"],
                      ["总之，先说结论。后面有三段细节。再后面是价格。"]),
    "colon_conclusion": (["说白了：就是贵。", "关键在于：坚持。"],
                         ["地址：北京路 18 号。", "时间：周六下午。"]),
    "punchline_ending": (["我们走了很远的路。最好的风景，就是身边的人。", "说完了。愿你被温柔以待。"],
                         ["我们走了很远的路。最后还是回家吃了碗面。", "最好的风景就是身边的人。然后我们去吃饭了。"]),
    "de_stacking": (["我的朋友的妈妈的店开在楼下，她家的猫的毛的颜色很怪。"],
                    ["我的朋友的妈妈的店开在楼下。", "的确，他的目的是打的士。"]),
    "bei_stack": (["他被骗了，钱也被拿走了。"],
                  ["他被骗了。\n钱也被拿走了。", "被子没叠，被窝还热。"]),
    "four_char_parallel": (["精挑细选，匠心打造，品质如一。专业设计，贴心呵护，安心之选。"],
                           ["精挑细选，匠心打造，品质如一。", "今天下雨，明天晴天。"]),
    "dash": (["他——我是说老王——没来。"],
             ["他——没来。\n老王——也没来。", "价格在 10—20 元之间。"]),
    "rhetorical_question": (["为什么？因为便宜。图什么？图个安心。"],
                            ["你吃了吗？吃了吗？", "为什么？因为便宜。\n图什么？图个安心。"]),
    "triple_parallel": (["更轻、更快、更省心。", "懂你的委屈，懂你的不甘，懂你的骄傲。",
                         "无论是在家，还是公司，亦或是路上，都能用。"],
                        ["苹果、香蕉和梨都在桌上。", "红烧肉、红烧鱼、红烧排骨，你选一个。",
                         "我没偷，我没拿，我什么都没干。", "更轻、更快。"]),
}


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule_hits(rule):
    for text in CASES[rule][0]:
        assert rule in rules_of(run(text)), text


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule_misses(rule):
    for text in CASES[rule][1]:
        assert rule not in rules_of(run(text)), text


def test_every_s2_rule_has_cases():
    assert set(CASES) == S2_RULES


def test_paragraph_tier_needs_two_in_same_paragraph():
    one = run("他被骗了。")
    two = run("他被骗了，又被罚了。")
    assert "bei_stack" not in rules_of(one)
    assert rules_of(two).count("bei_stack") == 2


def test_single_tier_flags_first_occurrence():
    assert rules_of(run("我们进行讨论。")).count("jinxing_verb") == 1


# --- profile 开关 ----------------------------------------------------------
def test_rule_off_skips_detection():
    r = run("这不是结束，而是开始。", profile={"rules": {"not_x_but_y": "off"}})
    assert r["hits"] == [] and "not_x_but_y" in r["metrics"]["rules_off"]


def test_rule_hint_lowers_severity():
    r = run("这不是结束，而是开始。", profile={"rules": {"not_x_but_y": "hint"}})
    assert [h["severity"] for h in r["hits"]] == ["hint"]


def test_unlisted_rule_defaults_on():
    r = run("这不是结束，而是开始。", profile={"rules": {"dash": "off"}})
    assert [h["severity"] for h in r["hits"]] == ["warn"]


def test_dialogue_profile_turns_dash_off():
    r = run("小雨：他——我是说老王——不在。", line="台词", profile=PROFILES["台词"])
    assert "dash" not in rules_of(r)


# --- 例外 ------------------------------------------------------------------
def _profile(line, *, rules=None, keep_exceptions=True, keep_fidelity=True):
    p = copy.deepcopy(PROFILES[line])
    if rules:
        p["rules"].update(rules)
    if not keep_exceptions:
        p["exceptions"] = []
    if not keep_fidelity:
        p.pop("fidelity", None)
    return p


def test_dash_interrupt_exception():
    text = "小雨：爸，我是说——算了——你别管了。"
    on = _profile("台词", rules={"dash": "on"})
    assert "dash" not in rules_of(run(text, "台词", on))
    no_exc = _profile("台词", rules={"dash": "on"}, keep_exceptions=False)
    assert rules_of(run(text, "台词", no_exc)).count("dash") == 2


def test_dash_at_line_end_is_interrupt():
    text = "老周：你听我说——\n小雨：不听——不听——"
    on = _profile("台词", rules={"dash": "on"})
    assert "dash" not in rules_of(run(text, "台词", on))


def test_dialogue_explanatory_dash_still_flagged_when_on():
    text = "老周：这把刀——祖上传下来的宝贝——值钱得很。"
    on = _profile("台词", rules={"dash": "on"})
    assert rules_of(run(text, "台词", on)).count("dash") == 2


def test_catchphrase_repeat_exception():
    text = "老周：得嘞，得嘞，得嘞。"
    assert "triple_parallel" not in rules_of(run(text, "台词", PROFILES["台词"]))
    assert "triple_parallel" in rules_of(run(text, "台词", _profile("台词", keep_exceptions=False)))


def test_short_fragment_exception():
    text = "小雨：去哪？回家。干嘛？睡觉。"
    p = _profile("台词", rules={"rhetorical_question": "on"})
    assert "rhetorical_question" not in rules_of(run(text, "台词", p))
    p2 = _profile("台词", rules={"rhetorical_question": "on"}, keep_exceptions=False)
    assert rules_of(run(text, "台词", p2)).count("rhetorical_question") == 2


def test_unfinished_line_exception():
    text = "林晚：我走了。\n陈默：真正的爱，从来不是……"
    assert "punchline_ending" not in rules_of(run(text, "台词", PROFILES["台词"]))
    assert "punchline_ending" in rules_of(run(text, "台词", _profile("台词", keep_exceptions=False)))


def test_speaker_prefix_is_not_a_colon_conclusion():
    r = run("答案：我不知道。\n关键：你别问了。", line="台词", profile=PROFILES["台词"])
    assert "colon_conclusion" not in rules_of(r)


def test_spoken_rhetorical_question_exception():
    text = "你是不是也这样？我也是。你说气不气？我反正挺气。"
    p = _profile("口播", rules={"rhetorical_question": "on"})
    assert "rhetorical_question" not in rules_of(run(text, "口播", p))
    p2 = _profile("口播", rules={"rhetorical_question": "on"}, keep_exceptions=False)
    assert rules_of(run(text, "口播", p2)).count("rhetorical_question") == 2


def test_spoken_rhetorical_exception_keeps_abstract_self_qa():
    text = "为什么它能做到？因为深耕十年。凭什么值得信赖？因为口碑说话。"
    hits = run(text, "口播", PROFILES["口播"])["hits"]
    assert [h["severity"] for h in hits if h["rule"] == "rhetorical_question"] == ["hint", "hint"]


def test_spoken_triple_exception():
    text = "更轻 180 克、更久 7 天、更静 35 分贝。"
    p = _profile("口播", rules={"triple_parallel": "on"})
    assert "triple_parallel" not in rules_of(run(text, "口播", p))
    p2 = _profile("口播", rules={"triple_parallel": "on"}, keep_exceptions=False)
    assert "triple_parallel" in rules_of(run(text, "口播", p2))


def test_short_repeat_exception():
    text = "买它，买它，买它。"
    p = _profile("口播", rules={"triple_parallel": "on"})
    assert "triple_parallel" not in rules_of(run(text, "口播", p))
    p2 = _profile("口播", rules={"triple_parallel": "on"}, keep_exceptions=False)
    assert "triple_parallel" in rules_of(run(text, "口播", p2))


def test_slogan_verbatim_exception():
    brief = SAMPLES["口播"]["brief"]
    text = "累了就歇会儿。与其硬扛，不如松一下。"
    keep = _profile("口播", keep_fidelity=False)
    assert "not_x_but_y" not in rules_of(run(text, "口播", keep, brief))
    drop = _profile("口播", keep_exceptions=False, keep_fidelity=False)
    assert "not_x_but_y" in rules_of(run(text, "口播", drop, brief))


def test_fidelity_exact_fields_are_protected():
    brief = {"locked": {"lines": ["真正的爱，从来不是占有。"]}}
    text = "林晚：我走了。\n陈默：真正的爱，从来不是占有。"
    p = PROFILES["台词"]
    assert "punchline_ending" not in rules_of(run(text, "台词", p, brief))
    assert "punchline_ending" in rules_of(run(text, "台词", p, {}))


# --- 样本 ------------------------------------------------------------------
@pytest.mark.parametrize("line", ["台词", "口播"])
def test_ai_tone_samples_hit_expected_rules(line):
    smp = SAMPLES[line]
    for item in smp["ai_tone"]:
        got = set(rules_of(run(item["text"], line, PROFILES[line], smp.get("brief"))))
        assert set(item["expect"]) <= got, (item["id"], set(item["expect"]) - got)


@pytest.mark.parametrize("line", ["台词", "口播"])
def test_natural_samples_have_no_warn_or_block(line):
    smp = SAMPLES[line]
    for item in smp["natural"]:
        hits = run(item["text"], line, PROFILES[line], smp.get("brief"))["hits"]
        bad = [h for h in hits if h["severity"] in ("block", "warn")]
        assert not bad, (item["id"], bad)


@pytest.mark.parametrize("line", ["台词", "口播"])
def test_natural_samples_cover_every_exception(line):
    covered = {c for item in SAMPLES[line]["natural"] for c in item["covers"]}
    declared = {e["id"] for e in PROFILES[line]["exceptions"]}
    # 下列例外不对应任何 S2 规则（合规、儿童内容由别的阶段处理），样本里不强求
    not_s2 = {"children_screen_recap", "first_episode", "action_line_adverbs", "keep_connectives"}
    assert declared - not_s2 <= covered


def test_samples_are_marked_self_written():
    for smp in SAMPLES.values():
        assert "自写示例" in smp["note"]
