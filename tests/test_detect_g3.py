"""G3 风格计量。样本都是自写示例。"""
import copy
import importlib
import json
from pathlib import Path

from detect import stages
from detect.g3 import METRIC_RULE, bleu, cv, mattr

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {line: json.loads((ROOT / "profiles" / f"{line}.json").read_text(encoding="utf-8"))
            for line in ("台词", "口播")}
SAMPLES = {line: json.loads((ROOT / "detect" / "samples" / f"{line}.json").read_text(encoding="utf-8"))
           for line in ("台词", "口播")}
AI_VO = SAMPLES["口播"]["ai_tone"][0]["text"]
NAT_VO = SAMPLES["口播"]["natural"][0]["text"]


def run(text, line="口播", profile=None, config=None, batch=None, brief=None):
    ctx = {"line": line, "text": text, "profile": profile if profile is not None else {},
           "brief": brief or {}, "round": 0, "history": [], "config": config or {}}
    if batch is not None:
        ctx["batch_texts"] = batch
    return stages.g3(ctx)


def test_importable_by_dotted_path():
    mod, fn = "detect.stages:g3".split(":")
    assert getattr(importlib.import_module(mod), fn) is stages.g3


def test_no_thresholds_always_pass_and_records_metrics():
    for text in (AI_VO, NAT_VO, "", "短。"):
        r = run(text, profile=PROFILES["口播"])
        assert r["stage"] == "G3" and r["kind"] == "soft"
        assert r["verdict"] == "pass" and r["route_to"] is None and r["hits"] == []
    m = run(AI_VO)["metrics"]
    for key in ("heading_per_kchar", "connector_per_kchar", "buzzword_per_kchar", "semicolon_per_kchar",
                "dunhao_per_kchar", "dash_per_kchar", "colon_per_kchar", "sentence_len_cv",
                "paragraph_len_cv", "char_mattr", "bigram_mattr"):
        assert key in m


def test_densities_per_kchar():
    text = "一、背景\n" + "这里是正文内容。" * 20 + "\n二、方法\n" + "首先，我们打造一个闭环；然后、再说。" * 5
    m = run(text, profile={})["metrics"]
    assert m["heading_per_kchar"] > 0
    assert m["connector_per_kchar"] > 0
    assert m["buzzword_per_kchar"] > 0
    assert m["semicolon_per_kchar"] > 0 and m["dunhao_per_kchar"] > 0


def test_connector_counted_only_at_clause_start_and_longest_match():
    m = run("总而言之，好。", profile={})["metrics"]
    assert m["connector_per_kchar"] == 200.0  # 1 个连接词 / 5 字
    assert run("他首先想到的不是钱。", profile={})["metrics"]["connector_per_kchar"] == 0


def test_dash_density_respects_interrupt_exception():
    text = "小雨：我是说——算了。\n老周：你——"
    assert run(text, "台词", PROFILES["台词"])["metrics"]["dash_per_kchar"] == 0
    p = copy.deepcopy(PROFILES["台词"])
    p["exceptions"] = []
    assert run(text, "台词", p)["metrics"]["dash_per_kchar"] > 0


def test_speaker_colon_not_counted():
    assert run("老周：吃了没？\n小雨：吃了。", "台词", PROFILES["台词"])["metrics"]["colon_per_kchar"] == 0


def test_protected_slogan_not_counted():
    brief = {"must_include": {"brand_terms": ["一站式打造好生活"]}}
    p = {"exceptions": [{"id": "slogan_verbatim"}]}
    assert run("我们的口号是一站式打造好生活。", profile=p, brief=brief)["metrics"]["buzzword_per_kchar"] == 0


def test_cv_needs_three_sentences_and_paragraphs():
    m = run("第一句话。第二句话。", profile={})["metrics"]
    assert m["sentence_len_cv"] is None and m["paragraph_len_cv"] is None
    m = run("短。\n这是一个长一些的句子。\n这是一个明显更长更长更长的句子啊。", profile={})["metrics"]
    assert m["sentence_len_cv"] is not None and m["paragraph_len_cv"] is not None


def test_diversity_needs_enough_chars():
    m = run("太短了，算不了。", profile={})["metrics"]
    assert m["char_mattr"] is None and m["bigram_mattr"] is None
    m = run(AI_VO, profile={})["metrics"]
    assert 0 < m["char_mattr"] <= 1 and 0 < m["bigram_mattr"] <= 1


def test_helpers():
    assert cv([5, 5, 5]) == 0
    assert cv([]) is None
    assert mattr(list("aaaa"), 2) == 0.5
    assert mattr(list("ab"), 3) is None
    same = list("今天天气很好我们去公园散步")
    assert abs(bleu(same, [same]) - 1.0) < 1e-9
    assert bleu(same, [list("完全不同的另一句话呢")]) < 0.2


def test_batch_metrics():
    other = "完全不同的另一份候选，讲的是同一台按摩仪，但每句话都换了说法，也换了顺序和例子。"
    r = run(AI_VO, profile={}, batch=[AI_VO, {"text": other}])
    m = r["metrics"]
    assert m["batch_size"] == 3
    assert 0 < m["batch_distinct_2"] < 1 and 0 < m["batch_self_bleu"] <= 1
    near_dup = run(AI_VO, profile={}, batch=[AI_VO])["metrics"]["batch_self_bleu"]
    diverse = run(AI_VO, profile={}, batch=[other])["metrics"]["batch_self_bleu"]
    assert near_dup > diverse
    assert r["verdict"] == "pass"


def test_batch_metrics_absent_without_batch():
    m = run(AI_VO, profile={})["metrics"]
    assert m["batch_self_bleu"] is None and m["batch_distinct_2"] is None


def test_threshold_exceeded_routes_to_s3_with_positions():
    cfg = {"thresholds": {"dash_per_kchar": {"max": 1}}}
    r = run(AI_VO, profile=PROFILES["口播"], config=cfg)
    assert r["verdict"] == "route" and r["route_to"] == "S3"
    dash_hits = [h for h in r["hits"] if h["rule"] == "dash"]
    assert len(dash_hits) == 2
    for h in dash_hits:
        assert AI_VO[h["span"][0]:h["span"][1]] == "——" and h["severity"] == "warn"
    assert r["metrics"]["exceeded"] == ["dash_per_kchar"]


def test_min_threshold_for_uniform_length():
    text = "我今天去了超市。买了一些水果。又买了一点菜。回家做了晚饭。"
    r = run(text, profile={}, config={"thresholds": {"sentence_len_cv": {"min": 0.5}}})
    assert r["verdict"] == "route"
    (h,) = r["hits"]
    assert h["rule"] == "uniform_length" and h["span"] == [0, len(text)]


def test_threshold_not_exceeded_passes():
    r = run(NAT_VO, profile=PROFILES["口播"], config={"thresholds": {"dash_per_kchar": {"max": 1}}})
    assert r["verdict"] == "pass" and r["hits"] == []


def test_hint_rule_threshold_reports_but_does_not_route():
    # 口播 profile 里 buzzword 是 hint
    r = run(AI_VO, profile=PROFILES["口播"], config={"thresholds": {"buzzword_per_kchar": {"max": 0}}})
    assert r["verdict"] == "pass" and r["route_to"] is None
    assert r["hits"] and all(h["severity"] == "hint" and h["rule"] == "buzzword" for h in r["hits"])


def test_off_rule_threshold_skipped():
    # 两条线的 profile 里 heading_density 都是 off
    text = "一、背景\n正文正文正文正文。\n二、方法\n正文正文正文正文。"
    r = run(text, profile=PROFILES["口播"], config={"thresholds": {"heading_per_kchar": {"max": 0}}})
    assert r["verdict"] == "pass" and r["hits"] == []
    assert "heading_per_kchar" in r["metrics"]["skipped_thresholds"]


def test_too_short_metric_skips_threshold():
    r = run("太短。", profile={}, config={"thresholds": {"sentence_len_cv": {"min": 0.5}}})
    assert r["verdict"] == "pass" and "sentence_len_cv" in r["metrics"]["skipped_thresholds"]


def test_unknown_threshold_ignored():
    r = run(AI_VO, profile={}, config={"thresholds": {"batch_self_bleu": {"max": 0}, "nope": 1}})
    assert r["verdict"] == "pass"
    assert set(r["metrics"]["skipped_thresholds"]) == {"batch_self_bleu", "nope"}


def test_metric_rule_map_uses_design_doc_ids():
    doc = (ROOT / "docs" / "工作流编排.md").read_text(encoding="utf-8")
    for rid in set(METRIC_RULE.values()):
        assert f"`{rid}`" in doc
