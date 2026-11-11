"""runner：阶段加载、顺序、轮次回流、报告、配置校验。"""
import copy

import pytest

from pipeline import config as cfgmod
from pipeline.adapters.base import SkillNotFound, resolve_skill
from pipeline.contract import ORDER, StageContractError, hit, result
from pipeline.runner import RunnerError, run_brief
from pipeline_helpers import DLG_PASS, HAS_DETECT, VO_PASS, brief, draft, example_config, load

VO_TEXT = draft(VO_PASS)
VO_BAD_FACT = draft("vo-example-01_保真不过.txt")


def fake(script=None, vendor="fake-a"):
    return {"adapter": "pipeline.adapters.fake:FakeAdapter", "model": "fake", "vendor": vendor,
            "params": {"script": script or {}}}


def make_cfg(line="口播", stages=None, max_rounds=2, rewrite=None, generate=None, judge=None, slots=None):
    raw = {
        "name": "测试配置", "line": line, "profile": f"profiles/{line}.json",
        "models": {"generator": fake({"generate": generate or []}), "rewriter": fake({"rewrite": rewrite or []}),
                   "judge": fake({"judge": judge or []}, vendor="fake-b")},
        "slots": slots or {"A": {"skills": ["baseline-none"]}, "B": {"skills": ["baseline-none"]},
                           "C": {"skills": ["baseline-none"]}, "D": {"max_rounds": max_rounds}},
        "stages": stages if stages is not None else {
            "S0": "pipeline.gates.brief:run",
            "G0": {"path": "pipeline.gates.format:run", "params": {"default_chars_per_min": 260}},
            "S3": "pipeline.adapters.stages:rewrite",
            "G1": "pipeline.gates.compliance:run",
            "G2": "pipeline.gates.fidelity:run",
        },
    }
    return cfgmod.from_dict(raw)


def stage_seq(draft_rep):
    return [(s["stage"], s["round"]) for s in draft_rep["stages"]]


# ---------------- 配置 ----------------

@pytest.mark.parametrize("name,line", [("口播-baseline-none", "口播"), ("台词-baseline-none", "台词")])
def test_example_configs_load(name, line, tmp_path):
    raw = load(f"configs/{name}.json")
    assert raw["stages"]["S2"] == "detect.stages:s2" and raw["stages"]["G3"] == "detect.stages:g3"
    assert raw["stages"]["G4"] is None
    cfg = cfgmod.load(example_config(name, tmp_path))
    assert cfg.line == line and cfg.max_rounds == 2
    assert ("S2" in cfg.stages) == HAS_DETECT and ("G3" in cfg.stages) == HAS_DETECT
    assert "G4" not in cfg.stages                                  # null → 跳过
    assert cfg.stages["S3"].adapter.slots["B"]["skills"][0].is_none
    assert cfg.warnings == []
    assert "盲审胜出后再填" in raw["slots"]["A"]["_待定"]


def test_resolve_skill_paths():
    assert resolve_skill("baseline-none").path is None
    assert resolve_skill("stop-slop-zh").path.parent.name == "variants"
    assert resolve_skill("humanizer-zh").path.parent.name == "upstream"
    assert resolve_skill("upstream/humanizer-zh").to_json()["path"] == "skills/upstream/humanizer-zh"
    assert resolve_skill("humanizer-zh").text().strip()
    assert resolve_skill("baseline-none").text() == ""
    with pytest.raises(SkillNotFound):
        resolve_skill("no-such-skill")


def test_unknown_skill_is_config_error():
    with pytest.raises(cfgmod.ConfigError, match="槽位 B"):
        make_cfg(slots={"B": {"skills": ["no-such-skill"]}, "D": {"max_rounds": 1}})


def test_bad_stage_path_is_config_error():
    with pytest.raises(cfgmod.ConfigError, match="nonexistent_mod"):
        make_cfg(stages={"S2": "nonexistent_mod.stages:run"})


@pytest.mark.skipif(HAS_DETECT, reason="只在没合 PR #6 时检查")
def test_example_config_without_detect_says_so():
    with pytest.raises(cfgmod.ConfigError, match="detect.stages"):
        cfgmod.load("configs/口播-baseline-none.json")


def test_profile_line_must_match():
    raw = {"line": "台词", "profile": "profiles/口播.json", "stages": {}}
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.from_dict(raw)


def test_same_vendor_judge_warns():
    raw = {"line": "口播", "models": {"generator": fake(), "rewriter": fake(), "judge": fake()},
           "slots": {"D": {"max_rounds": 1}}, "stages": {"G4": "pipeline.adapters.stages:judge"}}
    cfg = cfgmod.from_dict(raw)
    assert any("同一家厂商" in w for w in cfg.warnings)


# ---------------- 顺序与跳过 ----------------

def test_stage_order_and_skipping():
    seen = []

    def spy(name, kind):
        def fn(ctx):
            seen.append(name)
            assert set(ctx) >= {"line", "brief", "profile", "text", "round", "history", "batch_texts", "config"}
            assert ctx["config"] == {"x": name}
            return result(name, kind, "pass")
        return {"path": fn, "params": {"x": name}}

    kinds = {"S0": "hard", "G0": "hard", "S2": "report", "G1": "hard", "G2": "hard", "G3": "soft", "G5": "monitor"}
    stages = {k: spy(k, v) for k, v in kinds.items()}
    stages["S3"] = "pipeline.adapters.stages:rewrite"
    rep = run_brief(make_cfg(stages=stages), brief("口播"), [VO_TEXT, VO_TEXT])
    per_draft = ["G0", "S2", "G1", "G2", "G3", "G5"]
    assert seen == ["S0"] + per_draft * 2
    assert [s for s, _ in stage_seq(rep["drafts"][0])] == ["G0", "S2", "S3", "G1", "G2", "G3", "G5"]
    assert [x for x in ORDER if x in seen or x == "S3"] == ["S0", "G0", "S2", "S3", "G1", "G2", "G3", "G5"]


def test_batch_texts_are_the_other_drafts():
    got = []

    def g3(ctx):
        got.append(ctx["batch_texts"])
        return result("G3", "soft")

    run_brief(make_cfg(stages={"G3": g3}), brief("口播"), ["甲稿。", "乙稿。", "丙稿。"])
    assert got[0] == ["乙稿。", "丙稿。"] and got[1] == ["甲稿。", "丙稿。"]


def test_contract_violation_names_stage():
    with pytest.raises(StageContractError, match="G3"):
        run_brief(make_cfg(stages={"G3": lambda ctx: {"stage": "G3", "verdict": "ok"}}), brief("口播"), [VO_TEXT])
    with pytest.raises(StageContractError, match="span"):
        bad = lambda ctx: result("S2", "report", hits=[hit("dash", "x", "hint", span=[5, 2])])
        run_brief(make_cfg(stages={"S2": bad}), brief("口播"), [VO_TEXT])


def test_text_is_normalized_before_gates():
    seen = []

    def g0(ctx):
        seen.append(ctx["text"])
        return result("G0", "hard")

    run_brief(make_cfg(stages={"G0": g0}), brief("口播"), ["**示例牌暖手杯**,点下方链接!"])
    assert seen == ["示例牌暖手杯，点下方链接！"]


# ---------------- 结果与状态 ----------------

def test_passing_draft_report():
    rep = run_brief(make_cfg(), brief("口播"), [VO_TEXT], ["file:x.txt"])
    d = rep["drafts"][0]
    assert rep["status"] == "ok" and rep["brief_check"]["verdict"] == "pass"
    assert d["status"] == "passed" and d["rounds"] == 0 and d["layer1"] == {"survived": True, "eliminated_by": None}
    assert d["source"] == "file:x.txt" and d["draft_id"] == "vo-example-01#0"
    s3 = next(s for s in d["stages"] if s["stage"] == "S3")
    assert s3["metrics"]["called_model"] is False and s3["metrics"]["changed"] is False


def test_brief_returned_stops_everything():
    b = brief("口播")
    del b["must_include"]
    rep = run_brief(make_cfg(), b, [VO_TEXT])
    assert rep["status"] == "brief_returned" and rep["drafts"] == []


def test_g0_fail_eliminates_without_running_later_gates():
    rep = run_brief(make_cfg(), brief("口播"), [VO_TEXT * 3])
    d = rep["drafts"][0]
    assert d["status"] == "eliminated" and d["layer1"]["eliminated_by"] == "G0"
    assert stage_seq(d) == [("G0", 0)]


def test_g1_fail_eliminates():
    rep = run_brief(make_cfg(), brief("口播"), [draft("vo-example-01_合规不过.txt")])
    d = rep["drafts"][0]
    assert d["status"] == "eliminated" and d["layer1"]["eliminated_by"] == "G1"
    assert [s for s, _ in stage_seq(d)] == ["G0", "S3", "G1"]


def test_g1_review_marks_human_but_survives_layer1():
    text = VO_TEXT.replace("比我想的便宜", "我最喜欢这个颜色")
    d = run_brief(make_cfg(), brief("口播"), [text])["drafts"][0]
    assert d["status"] == "human" and d["layer1"]["survived"] is True
    assert d["needs_review"][0]["stage"] == "G1"


# ---------------- 轮次回流 ----------------

def test_g2_route_rewrite_fixes_then_reruns_g1_g2():
    cfg = make_cfg(rewrite=[{"replace": [["保温 8 小时", "保温 6 小时"]]}])
    d = run_brief(cfg, brief("口播"), [VO_BAD_FACT])["drafts"][0]
    assert d["status"] == "passed" and d["rounds"] == 1
    assert stage_seq(d) == [("G0", 0), ("S3", 0), ("G1", 0), ("G2", 0), ("S3", 1), ("G1", 1), ("G2", 1)]
    s3 = [s for s in d["stages"] if s["stage"] == "S3"][1]
    assert s3["metrics"]["from"] == "G2" and s3["metrics"]["called_model"] and s3["metrics"]["changed"]
    assert "保温 6 小时" in d["text_final"] and "保温 8 小时" in d["text_initial"]
    calls = cfg.stages["S3"].adapter.calls
    assert calls == [("rewrite", {"round": 1, "rules": ["g2.exact_missing", "g2.new_number"]})]


def test_g2_rounds_exhausted_goes_to_human_and_fails_layer1():
    d = run_brief(make_cfg(max_rounds=2), brief("口播"), [VO_BAD_FACT])["drafts"][0]
    assert d["rounds"] == 2 and d["status"] == "human"
    assert d["layer1"] == {"survived": False, "eliminated_by": "G2"}
    assert [r for s, r in stage_seq(d) if s == "G2"] == [0, 1, 2]
    assert [r for s, r in stage_seq(d) if s == "G1"] == [0, 1, 2]
    assert "上限 2" in d["needs_review"][-1]["reason"]


def test_max_rounds_zero_means_no_reroute():
    d = run_brief(make_cfg(max_rounds=0), brief("口播"), [VO_BAD_FACT])["drafts"][0]
    assert d["rounds"] == 0 and [s for s, _ in stage_seq(d)] == ["G0", "S3", "G1", "G2"]
    assert d["layer1"]["eliminated_by"] == "G2"


def test_no_s3_configured_means_no_reroute():
    stages = {"G2": "pipeline.gates.fidelity:run"}
    d = run_brief(make_cfg(stages=stages), brief("口播"), [VO_BAD_FACT])["drafts"][0]
    assert d["rounds"] == 0 and "没有 S3" in d["needs_review"][0]["reason"]


def test_rewrite_breaking_compliance_is_caught_on_rerun():
    cfg = make_cfg(rewrite=[{"replace": [["保温 8 小时", "保温 6 小时"], ["想要的", "全网第一，想要的"]]}])
    d = run_brief(cfg, brief("口播"), [VO_BAD_FACT])["drafts"][0]
    assert d["status"] == "eliminated" and d["layer1"]["eliminated_by"] == "G1"
    assert stage_seq(d)[-1] == ("G1", 1)


def g3_counter(n_fail):
    """前 n_fail 次打回 S3，之后放行。"""
    state = {"n": 0}

    def g3(ctx):
        state["n"] += 1
        if state["n"] <= n_fail:
            return result("G3", "soft", "route", "S3",
                          [hit("dash", "破折号太多", "warn", span=[0, 1], excerpt=ctx["text"][:1])])
        return result("G3", "soft")
    return g3


def test_g3_route_reruns_g1_g2_then_g3():
    stages = {"S3": "pipeline.adapters.stages:rewrite", "G1": "pipeline.gates.compliance:run",
              "G2": "pipeline.gates.fidelity:run", "G3": g3_counter(1)}
    cfg = make_cfg(stages=stages, rewrite=[VO_TEXT])
    d = run_brief(cfg, brief("口播"), [VO_TEXT])["drafts"][0]
    assert d["status"] == "passed" and d["rounds"] == 1
    assert stage_seq(d) == [("S3", 0), ("G1", 0), ("G2", 0), ("G3", 0), ("S3", 1), ("G1", 1), ("G2", 1), ("G3", 1)]
    assert cfg.stages["S3"].adapter.calls[0][1]["rules"] == ["dash"]


def test_g3_exhausted_is_human_but_survives_layer1():
    stages = {"S3": "pipeline.adapters.stages:rewrite", "G2": "pipeline.gates.fidelity:run", "G3": g3_counter(99)}
    d = run_brief(make_cfg(stages=stages, max_rounds=1), brief("口播"), [VO_TEXT])["drafts"][0]
    assert d["rounds"] == 1 and d["status"] == "human" and d["layer1"]["survived"] is True
    assert d["needs_review"][0]["stage"] == "G3"


def test_s2_hits_feed_first_rewrite():
    def s2(ctx):
        return result("S2", "report", hits=[hit("not_x_but_y", "删掉", "block", span=[0, 2], excerpt=ctx["text"][:2]),
                                            hit("connector_density", "只提示", "hint")])
    stages = {"S2": s2, "S3": "pipeline.adapters.stages:rewrite"}
    cfg = make_cfg(stages=stages, rewrite=["改过了。"])
    d = run_brief(cfg, brief("口播"), [VO_TEXT])["drafts"][0]
    assert d["text_final"] == "改过了。"
    assert cfg.stages["S3"].adapter.calls == [("rewrite", {"round": 0, "rules": ["not_x_but_y"]})]


def test_s2_reruns_after_every_rewrite_but_s3_only_gets_gate_hits():
    seen = []

    def s2(ctx):
        seen.append((ctx["round"], ctx["text"]))
        return result("S2", "report", hits=[hit("not_x_but_y", "删掉", "block", span=[0, 1], excerpt=ctx["text"][:1])])

    stages = {"S2": s2, "S3": "pipeline.adapters.stages:rewrite", "G1": "pipeline.gates.compliance:run",
              "G2": "pipeline.gates.fidelity:run"}
    cfg = make_cfg(stages=stages, rewrite=[VO_BAD_FACT, {"replace": [["保温 8 小时", "保温 6 小时"]]}])
    d = run_brief(cfg, brief("口播"), [VO_BAD_FACT])["drafts"][0]
    assert d["status"] == "passed" and d["rounds"] == 1
    assert stage_seq(d) == [("S2", 0), ("S3", 0), ("G1", 0), ("G2", 0),
                            ("S3", 1), ("S2", 1), ("G1", 1), ("G2", 1)]
    assert [r for r, _ in seen] == [0, 1] and "保温 6 小时" in seen[1][1]   # 第 1 轮的 S2 看的是改写后的文本
    calls = cfg.stages["S3"].adapter.calls
    assert calls[0][1]["rules"] == ["not_x_but_y"]                         # 第 0 轮：S2 的命中
    assert calls[1][1]["rules"] == ["g2.exact_missing", "g2.new_number"]   # 第 1 轮：只有打回它的 G2 的命中


# ---------------- 模型阶段 ----------------

def test_s1_generates_with_fake_adapter():
    stages = {"S0": "pipeline.gates.brief:run", "S1": {"path": "pipeline.adapters.stages:generate", "params": {"n": 2}},
              "G0": {"path": "pipeline.gates.format:run", "params": {"default_chars_per_min": 260}}}
    rep = run_brief(make_cfg(stages=stages, generate=[VO_TEXT, VO_TEXT * 3]), brief("口播"))
    assert rep["generation"]["metrics"]["n"] == 2
    assert [d["source"] for d in rep["drafts"]] == ["S1#0", "S1#1"]
    assert [d["status"] for d in rep["drafts"]] == ["passed", "eliminated"]


def test_no_text_and_no_s1_is_error():
    with pytest.raises(RunnerError):
        run_brief(make_cfg(), brief("口播"))


def test_skip_model_stages():
    cfg = make_cfg(rewrite=["不该被调用"])
    d = run_brief(cfg, brief("口播"), [VO_TEXT], skip={"S1", "S3", "G4"})["drafts"][0]
    assert "S3" not in [s for s, _ in stage_seq(d)] and cfg.stages["S3"].adapter.calls == []


def test_g4_uncalibrated_goes_to_human_and_calibrated_passes():
    stages = {"G4": "pipeline.adapters.stages:judge"}
    d = run_brief(make_cfg(stages=stages, judge=[{"verdict": "pass", "score": 0.9}]), brief("口播"), [VO_TEXT])["drafts"][0]
    assert d["status"] == "human" and d["stages"][-1]["metrics"]["calibrated"] is False
    stages = {"G4": {"path": "pipeline.adapters.stages:judge", "params": {"pass_at": 0.8, "rewrite_below": 0.3}}}
    d = run_brief(make_cfg(stages=stages, judge=[{"verdict": "pass", "score": 0.9}]), brief("口播"), [VO_TEXT])["drafts"][0]
    assert d["status"] == "passed"


def test_dialogue_line_end_to_end():
    stages = {"S0": "pipeline.gates.brief:run",
              "G0": {"path": "pipeline.gates.format:run", "params": {"default_chars_per_min": 200}},
              "G1": "pipeline.gates.compliance:run", "G2": "pipeline.gates.fidelity:run"}
    rep = run_brief(make_cfg("台词", stages=stages), brief("台词"),
                    [draft(DLG_PASS), draft("dlg-example-01_锁定台词被改.txt")])
    assert [d["status"] for d in rep["drafts"]] == ["passed", "eliminated"]
    g1 = next(s for s in rep["drafts"][0]["stages"] if s["stage"] == "G1")
    assert g1["metrics"]["enabled"] is False
