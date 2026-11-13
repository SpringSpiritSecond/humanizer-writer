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
    rep = run(p, tmp_path / "out", CFG, n=2, adapter=Fake([bad, good]), checker=None)
    assert [d["status"] for d in rep["drafts"]] == ["不过", "通过"]
    assert "suggested_order" not in rep
    md = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert good in md and "没做“多出来的内容”检查" in md


class Checker:
    def __init__(self, out):
        self.out = out

    def _chat(self, msgs, purpose):
        assert "左右脑" not in msgs[1]["content"]      # check_only 不给检查模型看
        return self.out


def test_extra_content_marks_to_confirm():
    text = "您说孩子跳绳手脚对不上。我们会让他做异侧拍，每组 16 下。我们已经给您寄了练习册。"
    r = check_draft(text, BRIEF, CFG, checker=Checker('[{"句子": "我们已经给您寄了练习册。", "多出来的": "寄了练习册"}]'))
    assert r["status"] == "待确认" and r["extra"][0]["多出来的"] == "寄了练习册"
    r2 = check_draft(text, BRIEF, CFG, checker=Checker("没有。[]"))
    assert r2["status"] == "通过" and r2["extra_checked"]
    r3 = check_draft(text, BRIEF, CFG, checker=Checker("乱码"))
    assert r3["status"] == "通过" and not r3["extra_checked"]   # 模型没给出结果，算没检查


def test_clock_minutes_are_not_new_numbers():
    b = {**BRIEF, "facts": [{"field": "时间", "value": "周四上午 9 点到下午 3 点"}]}
    r = check_draft("周四上午 9:00 到下午 3:00 停水。", b, CFG)
    assert not any("00" in f for f in r["flags"]) and r["pass"]


def test_chinese_numerals_count_as_written():
    b = {**BRIEF, "facts": [{"field": "停课", "value": "中间需要停 2 周的课"}, {"field": "时长", "value": "每次 15 分钟"},
                             {"field": "比例", "value": "复购占 38%"}]}
    r = check_draft("要停两周的课，每次十五分钟，复购占百分之三十八，也就是 38%。", b, CFG)
    assert r["pass"], r["fails"]
    r2 = check_draft("要停三周的课，每次十五分钟，复购 38%。", b, CFG)
    assert not r2["pass"] and any("2" in f for f in r2["fails"])
