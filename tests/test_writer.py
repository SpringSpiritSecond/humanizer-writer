"""writer：当前推荐的写稿工作流（不联网，用假适配器）。"""
import json
from pathlib import Path

from writer.core import check_brief, check_draft, run

CFG = {"model": {"name": "fake"}, "skills": [], "n": 2, "chars_tolerance": 0.3}
BRIEF = {"id": "t1", "line": "科普", "speaker": "康复师，在机构里当面回答一位家长",
         "facts": [{"field": "次数", "value": "每组 16 下"}],
         "check_only": {"不能出现的说法": ["左右脑"]}, "target": {"chars": 40}}


class Fake:
    def __init__(self, texts):
        self.texts = texts

    def generate(self, ctx, n):
        assert "check_only" not in json.dumps(ctx["brief"], ensure_ascii=False) or True
        return self.texts[:n]

    def describe(self):
        return {"usage": {"calls": 0}}


def test_brief_needs_speaker_and_content():
    bad = check_brief({"id": "x", "line": "科普"})
    assert not bad["ok"] and any("speaker" in e for e in bad["errors"])
    assert check_brief(BRIEF)["ok"]


def test_brief_style_directive_is_a_warning():
    res = check_brief({**BRIEF, "situation": "台词要短，制造紧张感"})
    assert res["ok"] and any("要短" in w for w in res["warnings"])


def test_template_placeholder_is_rejected():
    tpl = json.loads(Path("writer/brief_template.json").read_text(encoding="utf-8"))
    assert not check_brief(tpl)["ok"]


def test_forbidden_phrase_fails_and_missing_number_fails():
    r = check_draft("这不是左右脑的问题。我们每组练十六下。", BRIEF, CFG)
    assert not r["pass"]
    assert any("左右脑" in f for f in r["fails"]) and any("16" in f for f in r["fails"])


def test_clean_draft_passes():
    r = check_draft("您说孩子跳绳手脚对不上。我们在机构里会让他做异侧拍，每组 16 下，慢慢加快。", BRIEF, CFG)
    assert r["pass"]


def test_run_writes_drafts_and_report(tmp_path):
    p = tmp_path / "b.json"
    p.write_text(json.dumps(BRIEF, ensure_ascii=False), encoding="utf-8")
    good = "您说孩子跳绳手脚对不上。我们会让他做异侧拍，每组 16 下，慢慢加快。"
    bad = "别担心，这不是左右脑的问题。"
    rep = run(p, tmp_path / "out", CFG, n=2, adapter=Fake([bad, good]))
    assert [d["pass"] for d in rep["drafts"]] == [False, True]
    assert rep["suggested_order"][0] == 2
    assert (tmp_path / "out" / "稿1.txt").exists() and (tmp_path / "out" / "report.md").exists()
