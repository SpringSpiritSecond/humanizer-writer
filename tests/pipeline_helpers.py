"""pipeline 测试共用：示例 brief、profile、ctx 构造。"""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "pipeline" / "examples"


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def brief(line):
    return copy.deepcopy(load("pipeline/examples/briefs/" + ("vo-example-01.json" if line == "口播" else "dlg-example-01.json")))


def profile(line):
    return load(f"profiles/{line}.json")


def draft(name):
    return (EX / "drafts" / name).read_text(encoding="utf-8")


def ctx(line, text, b=None, p=None, config=None, **extra):
    from pipeline.textutil import normalize
    c = {"line": line, "brief": b if b is not None else brief(line), "profile": p if p is not None else profile(line),
         "text": normalize(text, line), "round": 0, "history": [], "batch_texts": [], "config": config or {}}
    c.update(extra)
    return c


VO_PASS = "vo-example-01_通过.txt"
DLG_PASS = "dlg-example-01_通过.txt"
