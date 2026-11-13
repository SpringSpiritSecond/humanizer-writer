"""把 <run>/blind.json 塞进审稿页模板：<run>/review-artifact.html（claude.ai 页面）和 <run>/<run名>-盲审.html（可直接发给人的独立文件）。

    python eval/scripts/build_review_artifact.py --run eval/out/bbtt-full

只放不透明编号、文本和 brief 的公开字段。出处（key.json / results.json）不进页面。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("review_artifact.html")
STANDALONE = Path(__file__).with_name("review_standalone.html")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    run = Path(a.run)
    blind = json.loads((run / "blind.json").read_text(encoding="utf-8"))
    for b in blind["briefs"]:
        b["brief"] = {k: v for k, v in b["brief"].items() if k not in ("brief_version", "id", "line")}
        for it in b["items"]:
            assert set(it) == {"vid", "text"}, "blind.json 里不应有出处字段"
    blind["pack"] = run.name
    payload = json.dumps(blind, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__BLIND_JSON__", payload)
    out = run / "review-artifact.html"
    out.write_text(html, encoding="utf-8")
    # 独立版：一个 .html 文件，发给谁都能双击打开评分，评完导出结果文件发回
    solo = run / f"{run.name}-盲审.html"
    solo.write_text(STANDALONE.read_text(encoding="utf-8").replace("__BLIND_JSON__", payload), encoding="utf-8")
    print(f"独立版：{solo}")
    n = sum(len(b["items"]) for b in blind["briefs"])
    print(f"{out}：{len(blind['briefs'])} 个 brief，{n} 份稿子，{len(html) // 1024} KB")


if __name__ == "__main__":
    main()
