"""CLI：用示例跑通 run → export → workbench import。"""
import json

from pipeline.__main__ import main as pipeline_main
from workbench.__main__ import main as workbench_main
from workbench.db import connect
from pipeline_helpers import ROOT

D = "pipeline/examples/drafts/"


def run_cli(tmp_path, cfg, brief, drafts, name, extra=()):
    out = tmp_path / f"{name}.json"
    args = ["run", "--config", f"configs/{cfg}.json", "--brief", f"pipeline/examples/briefs/{brief}.json",
            "--out", str(out), *extra]
    for d in drafts:
        args += ["--text-file", str(ROOT / D / d)]
    assert pipeline_main(args) == 0
    return out


def test_run_export_import(tmp_path, capsys):
    vo = run_cli(tmp_path, "口播-baseline-none", "vo-example-01",
                 ["vo-example-01_通过.txt", "vo-example-01_合规不过.txt", "vo-example-01_保真不过.txt"], "vo")
    dlg = run_cli(tmp_path, "台词-baseline-none", "dlg-example-01",
                  ["dlg-example-01_通过.txt", "dlg-example-01_锁定台词被改.txt"], "dlg", ["--gates-only"])
    rep = json.loads(vo.read_text(encoding="utf-8"))
    assert [d["status"] for d in rep["drafts"]] == ["passed", "eliminated", "human"]
    assert [d["layer1"]["eliminated_by"] for d in rep["drafts"]] == [None, "G1", "G2"]
    assert rep["config"]["name"] == "口播-baseline-none" and rep["drafts"][2]["rounds"] == 2
    rep_dlg = json.loads(dlg.read_text(encoding="utf-8"))
    assert rep_dlg["skipped_stages"] == ["G4", "S1", "S3"]
    assert "S3" not in [s["stage"] for s in rep_dlg["drafts"][0]["stages"]]

    wb = tmp_path / "wb.json"
    assert pipeline_main(["export", str(vo), str(dlg), "--out", str(wb)]) == 0
    data = json.loads(wb.read_text(encoding="utf-8"))
    assert data["is_example"] is True
    assert sorted(v["item_id"] for v in data["variants"]) == ["dlg-example-01", "vo-example-01"]
    assert len(data["_skipped"]) == 3
    v = next(v for v in data["variants"] if v["item_id"] == "vo-example-01")
    assert v["source_type"] == "candidate" and v["candidate_id"] == "口播-baseline-none"
    assert v["params"]["status"] == "passed" and v["sample_idx"] == 0

    db = tmp_path / "wb.sqlite3"
    assert workbench_main(["--db", str(db), "import", str(wb)]) in (None, 0)
    conn = connect(db)
    items = conn.execute("SELECT id, is_example FROM item ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in items] == [("dlg-example-01", 1), ("vo-example-01", 1)]
    rows = conn.execute("SELECT v.item_id, s.source_type, s.source_label, v.display_text, v.raw_text "
                        "FROM variant v JOIN variant_source s ON s.variant_id = v.id ORDER BY v.item_id").fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [("dlg-example-01", "candidate", "台词-baseline-none"),
                                                   ("vo-example-01", "candidate", "口播-baseline-none")]
    # pipeline 用的是和工作台同一套统一格式，导入后展示文本不变，span 下标对得上
    assert all(r[3] == r[4] for r in rows)
    conn.close()


def test_export_exclude_review(tmp_path):
    vo = run_cli(tmp_path, "口播-baseline-none", "vo-example-01", ["vo-example-01_通过.txt"], "vo")
    rep = json.loads(vo.read_text(encoding="utf-8"))
    rep["drafts"][0]["status"] = "human"
    vo.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "wb.json"
    assert pipeline_main(["export", str(vo), "--exclude-review", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["variants"] == []


def test_run_brief_returned_exit_code(tmp_path):
    bad = tmp_path / "bad.json"
    b = json.loads((ROOT / "pipeline/examples/briefs/vo-example-01.json").read_text(encoding="utf-8"))
    del b["must_include"]
    bad.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    code = pipeline_main(["run", "--config", "configs/口播-baseline-none.json", "--brief", str(bad),
                          "--text-file", str(ROOT / D / "vo-example-01_通过.txt"), "--out", str(tmp_path / "r.json")])
    assert code == 3


def test_run_bad_config_exit_code(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"line": "口播", "stages": {"S2": "detect.stages:s2"}}), encoding="utf-8")
    assert pipeline_main(["run", "--config", str(cfg), "--brief", "pipeline/examples/briefs/vo-example-01.json",
                          "--text-file", str(ROOT / D / "vo-example-01_通过.txt")]) == 2
