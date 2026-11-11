"""作答校验、格式统一、导出、分析，以及完整流程。"""
import csv
import io
import json

import pytest

from workbench import analysis, batching, exporter, importer, service, simulate
from workbench.normalize import normalize
from conftest import call


# ---------- 格式统一 ----------

def test_normalize_markdown_and_punct():
    s = normalize("## 标题\n\n**你好**,我是谁?\n- 第一条\n1. 第二条\n他说:\"走吧\"...", "口播")
    assert s == "标题\n\n你好，我是谁？\n第一条\n第二条\n他说：“走吧”……"


def test_normalize_keeps_numbers():
    assert normalize("原价 1,299 元,10:30 开抢", "口播") == "原价 1,299 元，10:30 开抢"


def test_normalize_script_lines():
    s = normalize("小周: 行吧\n[小周转身]\n(阿琳关门)\n阿琳 ：等等--", "台词")
    assert s == "小周：行吧\n（小周转身）\n（阿琳关门）\n阿琳：等等——"


# ---------- 导入 ----------

def test_import_rejects_bad_rows(conn):
    with pytest.raises(importer.ImportErrorWB):
        importer.import_json(conn, {"variants": [{"item_id": "nope", "text": "x", "source_type": "human"}]})
    with pytest.raises(importer.ImportErrorWB):
        importer.import_json(conn, {"variants": [{"item_id": "vo-demo-01", "text": "x", "source_type": "candidate"}]})


def test_csv_candidate_label(conn):
    labels = {r[0] for r in conn.execute("SELECT source_label FROM variant_source WHERE source_type='candidate'")}
    assert labels == {"示例候选-甲", "示例候选-乙"}


# ---------- 作答 ----------

def test_judgment_validation_and_order(conn, rater, app):
    batching.generate_batch(conn, rater["id"], "台词", n_pairwise=8, n_single=2, seed=1)
    pair = conn.execute("SELECT public_id FROM task WHERE kind='pairwise_pref' LIMIT 1").fetchone()[0]
    single = conn.execute("SELECT public_id FROM task WHERE kind='single_turing' LIMIT 1").fetchone()[0]
    url = f"/api/rater/task/{pair}/judgment"
    # 没打判别分不能只给偏好
    assert call(app, "POST", url, code=rater["code"], body={"preference": "A", "duration_ms": 30000})[0] == 400
    assert call(app, "POST", url, code=rater["code"], body={"ai_conf_a": 2, "preference": "A", "duration_ms": 30000})[0] == 400
    assert call(app, "POST", url, code=rater["code"], body={"ai_conf_a": 2, "ai_conf_b": 6, "preference": "A", "duration_ms": 30000})[0] == 400
    assert call(app, "POST", url, code=rater["code"], body={"ai_conf_a": 2, "ai_conf_b": 4, "duration_ms": 30000})[0] == 400
    st, r = call(app, "POST", url, code=rater["code"], body={
        "ai_conf_a": 2, "ai_conf_b": 4, "preference": "A", "duration_ms": 30000,
        "tags": {"A": ["套话", "不存在的标签"], "B": ["电报体"]},
        "spans": [{"side": "B", "start": 0, "end": 3, "text": "abc", "tag": "电报体"}], "reason": "测试"})
    assert st == 200 and r["too_fast"] is False
    j = conn.execute("SELECT * FROM judgment").fetchone()
    assert json.loads(j["tags_json"]) == {"A": ["套话"], "B": ["电报体"]}
    # 单篇题只需判别
    st, r = call(app, "POST", f"/api/rater/task/{single}/judgment", code=rater["code"],
                 body={"ai_conf_a": 5, "duration_ms": 1200})
    assert st == 200 and r["too_fast"] is True


def test_too_fast_rule():
    assert service.too_fast(3000, 50)
    assert service.too_fast(6000, 300)      # 3000 字/分
    assert not service.too_fast(20000, 200)


# ---------- 分析 ----------

def test_krippendorff_reference_values():
    """Krippendorff (2011) 'Computing Krippendorff's Alpha-Reliability' 的示例数据。"""
    N = None
    coders = [
        [1, 2, 3, 3, 2, 1, 4, 1, 2, N, N, N],
        [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, N, 3],
        [N, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, N],
        [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, N],
    ]
    units = {u: [c[u] for c in coders if c[u] is not None] for u in range(12)}
    assert analysis.krippendorff_alpha(units, "nominal") == pytest.approx(0.743, abs=1e-3)
    assert analysis.krippendorff_alpha(units, "ordinal") == pytest.approx(0.815, abs=1e-3)
    assert analysis.krippendorff_alpha(units, "interval") == pytest.approx(0.849, abs=1e-3)


def test_bt_orders_systems():
    games = [("x", "y", 1)] * 30 + [("y", "x", 1)] * 10 + [("y", "z", 1)] * 30 + [("z", "y", 1)] * 10 + [("x", "z", 0.5)] * 4
    s = analysis.bt_fit(games, ["x", "y", "z"])
    assert s["x"] > s["y"] > s["z"]
    assert abs(sum(s.values()) / 3 - 1000) < 1e-6


def test_binom():
    assert analysis.binom_two_sided(5, 10) == pytest.approx(1.0)
    assert analysis.binom_two_sided(0, 10) == pytest.approx(2 / 1024)


# ---------- 完整流程 ----------

def test_full_flow(conn, app):
    # 导入（JSON 和 CSV 在 fixture 里已导）→ 建评审 → 批次 → 作答 → 导出 → 分析
    st, r = call(app, "POST", "/api/admin/raters", admin="admintok", body={"name": "真人演示"})
    assert st == 200
    st, b = call(app, "POST", "/api/admin/batches", admin="admintok",
                 body={"rater_id": r["id"], "line": "口播", "n_pairwise": 12, "n_single": 2, "seed": 4})
    assert st == 200
    for k in range(3):
        rid = simulate.ensure_sim_rater(conn, f"模拟{k}")
        for line in ("台词", "口播"):
            batching.generate_batch(conn, rid, line, n_pairwise=20, n_single=4, seed=k)
        simulate.simulate(conn, rid, seed=k)
    simulate.simulate(conn, r["id"], seed=99)  # 让“真人演示”也有作答（同样是模拟出来的）

    st, csv_text = call(app, "GET", "/api/admin/export/csv", admin="admintok")
    assert st == 200
    rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("﻿"))))
    n_j = conn.execute("SELECT COUNT(*) FROM judgment").fetchone()[0]
    assert len(rows) == n_j
    assert {"a_source_label", "b_source_label", "a_skill_git_hash", "preferred_source", "too_fast"} <= set(rows[0])

    st, jl = call(app, "GET", "/api/admin/export/jsonl", admin="admintok")
    assert len(jl.strip().split("\n")) == n_j

    prefs = [json.loads(l) for l in exporter.to_preference_jsonl(conn, include_simulated=True).strip().split("\n")]
    assert prefs and all({"prompt", "chosen", "rejected", "meta"} <= set(p) for p in prefs)
    assert all(p["chosen"] != p["rejected"] for p in prefs)
    assert all(p["meta"]["chosen_source"] != "gold_bad" for p in prefs)
    # 默认不含模拟评审
    real_only = exporter.to_preference_jsonl(conn)
    assert all(not json.loads(l)["meta"]["rater_simulated"] for l in real_only.strip().split("\n") if l)

    rep = analysis.analyze(conn, n_boot=100, write_back=True)
    md = analysis.to_markdown(rep)
    assert "示例数据" in md and "Krippendorff" in md
    for ln in rep["lines"]:
        sy = ln["systems"]
        assert {"human", "raw_ai_baseline", "示例候选-甲"} <= set(sy)
        assert sy["raw_ai_baseline"]["detection_rate"] > sy["human"]["detection_rate"]
        assert sy["human"]["relative_to_anchors"] == 0
        assert sy["raw_ai_baseline"]["relative_to_anchors"] == 1
        lo, hi = sy["示例候选-甲"]["bt_ci"]
        assert lo <= sy["示例候选-甲"]["bt"] <= hi
        assert sy["示例候选-甲"]["bt"] > sy["raw_ai_baseline"]["bt"]
        assert "判别分（有序）" in ln["alpha"]
    q = rep["raters"]
    has_repeat = {r[0] for r in conn.execute("SELECT DISTINCT rater_id FROM task WHERE control_type='repeat'")}
    assert has_repeat
    assert all(q[rid]["self_consistency"] is not None for rid in has_repeat)
    assert conn.execute("SELECT COUNT(*) FROM rater WHERE stats_updated_at IS NOT NULL").fetchone()[0] == len(q)

    st, a = call(app, "GET", "/api/admin/analysis", admin="admintok", query={"n_boot": ["50"]})
    assert st == 200 and "BT 分" in a["markdown"]
