"""S0 / G0 / G1 / G2：每道闸门都有通过和不通过的用例。"""
import copy

import pytest

from pipeline.contract import validate
from pipeline.gates import brief as s0
from pipeline.gates import compliance as g1
from pipeline.gates import fidelity as g2
from pipeline.gates import format as g0
from pipeline.textutil import cn2num, numbers, spoken_chars
from pipeline_helpers import DLG_PASS, VO_PASS, brief, ctx, draft, load, profile

VO_TEXT = draft(VO_PASS)
DLG_TEXT = draft(DLG_PASS)


def rules(res, severity=None):
    return [h["rule"] for h in res["hits"] if severity is None or h["severity"] == severity]


# ---------------- S0 ----------------

@pytest.mark.parametrize("line", ["口播", "台词"])
def test_s0_pass_on_example_briefs(line):
    res = validate(s0.run(ctx(line, "")), "S0")
    assert res["verdict"] == "pass", res["hits"]


def test_s0_fail_missing_cta_and_facts():
    b = brief("口播")
    del b["must_include"]["cta"]
    b["facts"] = []
    res = s0.run(ctx("口播", "", b))
    assert res["verdict"] == "fail"
    fields = {h.get("field") for h in res["hits"] if h["severity"] == "block"}
    assert {"must_include.cta", "facts"} <= fields


def test_s0_fail_missing_scene_card_beats_and_names():
    b = brief("台词")
    b["scene_card"]["beats"] = []
    b["scene_card"]["characters"][1]["name"] = ""
    res = s0.run(ctx("台词", "", b))
    assert res["verdict"] == "fail"
    fields = {h.get("field") for h in res["hits"] if h["severity"] == "block"}
    assert "scene_card.beats" in fields and "scene_card.characters[1].name" in fields


@pytest.mark.parametrize("line", ["口播", "台词"])
def test_s0_fail_on_untouched_template(line):
    tpl = load(f"eval/briefs/{line}/_template.json")
    res = s0.run(ctx(line, "", tpl))
    assert res["verdict"] == "fail"
    assert "s0.placeholder" in rules(res)


def test_s0_fail_line_mismatch():
    res = s0.run(ctx("台词", "", brief("口播")))
    assert res["verdict"] == "fail" and rules(res) == ["s0.line_mismatch"]


def test_s0_optional_missing_is_warning_only():
    b = brief("台词")
    del b["locked"]
    res = s0.run(ctx("台词", "", b))
    assert res["verdict"] == "pass"
    assert "s0.optional_missing" in rules(res, "warn")


# ---------------- G0 ----------------

def test_g0_pass_with_estimated_cpm_warning():
    res = validate(g0.run(ctx("口播", VO_TEXT, config={"default_chars_per_min": 260})), "G0")
    assert res["verdict"] == "pass"
    assert "g0.chars_per_min_estimated" in rules(res, "warn")
    assert res["metrics"]["chars_per_min_from"] == "estimate"


def test_g0_uses_brief_cpm_without_warning():
    b = brief("口播")
    b["target"]["chars_per_min"] = 260
    res = g0.run(ctx("口播", VO_TEXT, b))
    assert res["verdict"] == "pass"
    assert "g0.chars_per_min_estimated" not in rules(res)
    assert res["metrics"]["chars_per_min_from"] == "brief"


def test_g0_uses_profile_cpm():
    p = profile("口播")
    p["length"]["chars_per_min"] = 260
    res = g0.run(ctx("口播", VO_TEXT, p=p))
    assert res["metrics"]["chars_per_min_from"] == "profile" and res["verdict"] == "pass"


def test_g0_fail_too_long():
    res = g0.run(ctx("口播", VO_TEXT * 3, config={"default_chars_per_min": 260}))
    assert res["verdict"] == "fail"
    assert "g0.length" in rules(res, "block")


def test_g0_fail_too_short_dialogue():
    res = g0.run(ctx("台词", "小唐：这箱是我的，上面写着三楼。", config={"default_chars_per_min": 200}))
    assert res["verdict"] == "fail" and "g0.length" in rules(res, "block")


def test_g0_dialogue_counts_only_spoken_chars():
    text = "（一段很长很长很长很长很长很长的动作线）\n小唐：好。"
    assert spoken_chars(text, "台词") == 1


def test_g0_fail_missing_brand_and_cta():
    text = VO_TEXT.replace("示例牌暖手杯", "这个杯子").replace("点下方链接", "去看看")
    res = g0.run(ctx("口播", text, config={"default_chars_per_min": 260}))
    assert res["verdict"] == "fail"
    missing = {h["field"] for h in res["hits"] if h["rule"] == "g0.must_include"}
    assert missing == {"must_include.brand_terms[0]", "must_include.cta"}


def test_g0_pass_dialogue_and_fail_locked_line():
    ok = g0.run(ctx("台词", DLG_TEXT, config={"default_chars_per_min": 200}))
    assert ok["verdict"] == "pass", ok["hits"]
    bad = g0.run(ctx("台词", draft("dlg-example-01_锁定台词被改.txt"), config={"default_chars_per_min": 200}))
    assert bad["verdict"] == "fail" and "g0.locked_line" in rules(bad, "block")


def test_g0_fail_must_not_literal():
    text = VO_TEXT.replace("比我想的便宜", "冬天最保温的就是它")
    res = g0.run(ctx("口播", text, config={"default_chars_per_min": 260}))
    assert res["verdict"] == "fail"
    h = next(h for h in res["hits"] if h["rule"] == "g0.must_not")
    assert h["excerpt"] == "最保温" and res["metrics"]["blocking"] == 1


def test_g0_single_char_must_not_only_warns():
    b = brief("口播")
    b["must_not"] = ["“最”“第一”等极限词"]
    text = VO_TEXT.replace("比我想的便宜", "最近卖得不错")
    res = g0.run(ctx("口播", text, b, config={"default_chars_per_min": 260}))
    assert res["verdict"] == "pass"
    assert "g0.must_not" in rules(res, "warn")


# ---------------- G1 ----------------

def g1_run(text, b=None, p=None):
    return validate(g1.run(ctx("口播", text, b, p)), "G1")


def test_g1_disabled_for_dialogue():
    res = validate(g1.run(ctx("台词", "这是全网第一的国家级蛋糕。")), "G1")
    assert res["verdict"] == "pass" and res["metrics"]["enabled"] is False and res["hits"] == []


def test_g1_pass_clean_text():
    res = g1_run(VO_TEXT)
    assert res["verdict"] == "pass" and res["hits"] == []


@pytest.mark.parametrize("phrase", ["国家级", "最佳", "全网销量第一", "首选", "顶级", "唯一"])
def test_g1_fail_absolute_terms(phrase):
    res = g1_run(f"这款杯子是{phrase}的。")
    assert res["verdict"] == "fail"
    assert "g1.absolute_term" in rules(res, "block")
    assert all(h["span"] is not None for h in res["hits"])


@pytest.mark.parametrize("text", ["最近天冷了，早上骑车手冻。", "第一集里他就出场了。", "我第一次用的时候没想到。",
                                  "最后一天发货，下周不发了。"])
def test_g1_exclusions_are_not_hits(text):
    res = g1_run(text)
    assert res["verdict"] == "pass", res["hits"]


def test_g1_span_points_at_term():
    text = "冬天通勤的最佳选择。"
    res = g1_run(text)
    s, e = res["hits"][0]["span"]
    assert text[s:e] == "最佳"


@pytest.mark.parametrize("text,exemption", [
    ("这是我们家这几款里最轻的一只。", "self_comparison"),
    ("热饮最佳饮用温度在 60 度左右。", "usage_tip"),
    ("按国家标准，这台属于能效最高级。", "standard_grade"),
    ("这个型号叫“顶级款”，是厂家起的名字。", "model_or_trademark"),
])
def test_g1_exempt_zone_goes_to_review(text, exemption):
    res = g1_run(text)
    assert res["verdict"] == "review" and res["route_to"] == "human", res["hits"]
    assert any(h.get("exemption") == exemption for h in res["hits"])
    assert "g1.absolute_term" not in rules(res, "block")


def test_g1_brand_name_containing_term_goes_to_review():
    b = brief("口播")
    b["must_include"]["brand_terms"] = ["第一鲜果铺"]
    res = g1_run("第一鲜果铺今天开门。", b)
    assert res["verdict"] == "review"
    assert res["hits"][0]["exemption"] == "model_or_trademark"


def test_g1_fuzzy_zui_goes_to_review():
    res = g1_run("我最喜欢早上喝一口热的。")
    assert res["verdict"] == "review" and rules(res) == ["g1.fuzzy"]


def test_g1_block_beats_review():
    res = g1_run("我最喜欢它，也是全网第一。")
    assert res["verdict"] == "fail"


def test_g1_industry_pending_hint():
    p = profile("口播")
    p["compliance"]["industries"] = ["保健食品"]
    res = g1_run(VO_TEXT, p=p)
    assert res["verdict"] == "pass" and "g1.industry_pending" in rules(res, "hint")


def test_g1_dictionary_marks_industry_rules_pending():
    d = g1.load_dictionary()
    assert "待法务补" in d["待补"]


# ---------------- G2 ----------------

def g2_run(line, text, b=None, p=None, config=None):
    return validate(g2.run(ctx(line, text, b, p, config)), "G2")


def test_g2_pass_examples():
    assert g2_run("口播", VO_TEXT)["verdict"] == "pass"
    res = g2_run("台词", DLG_TEXT)
    assert res["verdict"] == "pass", res["hits"]
    assert res["metrics"]["beats"]["checked"] is False and res["metrics"]["beats"]["count"] == 3


def test_g2_fact_changed_routes_to_s3_with_field():
    res = g2_run("口播", draft("vo-example-01_保真不过.txt"))
    assert res["verdict"] == "route" and res["route_to"] == "S3"
    h = next(h for h in res["hits"] if h["rule"] == "g2.exact_missing")
    assert h["field"] == "facts[1].value" and "保温" in h["message"] and h["expected"] == "保温 6 小时"
    assert "facts[1].value" in res["metrics"]["fields"]
    assert "g2.new_number" in rules(res)


def test_g2_must_match_false_is_skipped():
    b = brief("口播")
    b["facts"][1]["must_match"] = False
    text = VO_TEXT.replace("保温 6 小时", "能热一上午")
    assert g2_run("口播", text, b)["verdict"] == "pass"


def test_g2_new_number_flagged_with_span():
    text = VO_TEXT.replace("比我想的便宜", "一年能用 300 天")
    res = g2_run("口播", text)
    assert res["verdict"] == "route"
    h = next(h for h in res["hits"] if h["rule"] == "g2.new_number")
    assert res and text_at(text, h) == "300"


def text_at(text, h):
    from pipeline.textutil import normalize
    t = normalize(text, "口播")
    return t[h["span"][0]:h["span"][1]]


def test_g2_chinese_number_counts():
    text = VO_TEXT.replace("比我想的便宜", "三天就离不开")
    res = g2_run("口播", text)
    assert any(h["rule"] == "g2.new_number" and h["excerpt"] == "三" for h in res["hits"])


@pytest.mark.parametrize("claim", ["保证不烫手", "不满意包退", "7 天见效", "终身保修"])
def test_g2_new_claims(claim):
    text = VO_TEXT.replace("比我想的便宜", claim)
    res = g2_run("口播", text)
    assert res["verdict"] == "route" and "g2.new_claim" in rules(res)


def test_g2_claim_in_brief_is_allowed():
    b = brief("口播")
    b["facts"].append({"field": "售后", "value": "7 天无理由退货", "must_match": True})
    text = VO_TEXT.replace("比我想的便宜", "7 天无理由退货")
    res = g2_run("口播", text, b)
    assert res["verdict"] == "pass", res["hits"]


def test_g2_forbidden_rechecked_after_rewrite():
    text = VO_TEXT.replace("比我想的便宜", "冬天最保温")
    res = g2_run("口播", text)
    assert res["verdict"] == "route" and "g2.forbidden" in rules(res)


@pytest.mark.parametrize("old,new,field", [
    ("快递箱", "纸箱", "locked.props_and_names[0]"),
    ("这箱是我的，上面写着三楼。", "这是我的。", "locked.lines[0]"),
    ("老林", "老李", "scene_card.characters[0].name"),
])
def test_g2_dialogue_locked_and_names(old, new, field):
    text = DLG_TEXT.replace(old, new)
    res = g2_run("台词", text)
    assert res["verdict"] == "route" and res["route_to"] == "S3"
    assert field in {h["field"] for h in res["hits"]}


def test_g2_dialogue_does_not_check_numbers():
    text = DLG_TEXT.replace("以后常见", "我住了 3 年了")
    assert g2_run("台词", text)["verdict"] == "pass"


def test_g2_beat_checker_hook():
    from pipeline.contract import hit

    def checker(c, beats):
        return [hit("g2.beat_lost", f"beat 丢了：{beats[2]}", field="scene_card.beats[2]")]

    res = g2_run("台词", DLG_TEXT, config={"beat_checker": checker})
    assert res["verdict"] == "route" and res["metrics"]["beats"]["checked"] is True
    assert res["hits"][0]["field"] == "scene_card.beats[2]"


# ---------------- 文本工具 ----------------

@pytest.mark.parametrize("s,v", [("三", 3), ("十五", 15), ("二十", 20), ("一百二十", 120), ("两万", 20000), ("二〇二六", 2026)])
def test_cn2num(s, v):
    assert cn2num(s) == v


def test_numbers_ignore_common_words():
    assert numbers("一起去，一下就好，千万别忘了，第一次") == []
    assert [n["value"] for n in numbers("1,000 块和两杯")] == [1000.0, 2.0]
