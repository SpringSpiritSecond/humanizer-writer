"""审完以后揭晓：把评分和 key.json 对上，按组合汇总（支持多人）。

    python eval/scripts/reveal.py --run eval/out/bbtt-full

评分来源：<run>/ratings/*.json（多人，每人一个文件）；没有这个目录时读旧的 <run>/ratings.json（单人）。
输出 <run>/reveal.md（同时打印）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

LINES = ("台词", "科普", "训练", "口播")


def load_raters(run: Path) -> list[tuple[str, dict]]:
    d = run / "ratings"
    if d.is_dir():
        out = []
        for f in sorted(d.glob("*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            # 从在线审稿页导出的文档可能多包一层（{"data": {"name", "data"}}）
            inner = rec.get("data")
            if isinstance(inner, dict) and isinstance(inner.get("data"), dict) and "name" in inner:
                rec = inner
            out.append((rec.get("name") or f.stem[:6], rec.get("data") or {}))
        return out
    f = run / "ratings.json"
    return [("单人", json.loads(f.read_text(encoding="utf-8")))] if f.exists() else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    run = Path(a.run)
    key = json.loads((run / "key.json").read_text(encoding="utf-8"))
    results = {r.get("vid"): r for r in json.loads((run / "results.json").read_text(encoding="utf-8")) if r.get("vid")}
    raters = load_raters(run)

    arm = defaultdict(lambda: {"ai": [], "talk": [], "good": [], "best": 0, "tags": defaultdict(int), "line": None})
    cell = defaultdict(lambda: {"ai": [], "talk": [], "good": [], "notes": []})   # (brief, arm)
    rated_by = defaultdict(set)
    for who, data in raters:
        for bid, br in data.items():
            for vid, r in (br.get("items") or {}).items():
                k, res = key.get(vid), results.get(vid, {})
                if not k:
                    continue
                name, line = k["arm"], res.get("line")
                A, C = arm[(line, name)], cell[(bid, name)]
                A["line"] = line
                for f in ("ai", "talk", "good"):
                    if r.get(f):
                        A[f].append(r[f])
                        C[f].append(r[f])
                for t in r.get("tags", []):
                    A["tags"][t] += 1
                if r.get("note"):
                    C["notes"].append(f"{who}：{r['note']}")
                rated_by[bid].add(who)
            if br.get("best") in key:
                arm[(results.get(br["best"], {}).get("line"), key[br["best"]]["arm"])]["best"] += 1

    metrics = defaultdict(list)
    for vid, r in results.items():
        if r.get("g3_metrics"):
            metrics[(r["line"], r["arm"])].append(r["g3_metrics"])

    avg = lambda xs: f"{sum(xs) / len(xs):.2f}" if xs else "—"

    def mm(line, name, k):
        return avg([m[k] for m in metrics[(line, name)] if isinstance(m.get(k), (int, float))])

    out = ["# 盲审揭晓", "",
           f"评审 {len(raters)} 人：{'、'.join(w for w, _ in raters) or '（无）'}。",
           "AI 感：1 = 肯定是人写的，5 = 肯定是 AI（越低越好）。对人说话：1 = 像念给旁观者听，5 = 就是在跟对方说（越高越好）。"
           "质量：1 = 不能用，5 = 可以直接用（越高越好）。n 是评分次数。感叹 / 碎句 / 口令是检测脚本算的句子占比，只作参考。"
           "每个组合每条线只有 3 份稿子，评审人数少时差距不大就不要当结论。", ""]
    for line in LINES:
        rows = {n: v for (l, n), v in arm.items() if l == line}
        if not rows:
            continue
        out += [f"## {line}", "", "| 组合 | 质量 | 对人说话 | AI 感 | n | 最好 | 感叹 | 碎句 | 口令 | 常见标签 |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for n, v in sorted(rows.items(), key=lambda kv: -(sum(kv[1]["good"]) / len(kv[1]["good"]) if kv[1]["good"] else 0)):
            tags = "、".join(f"{t}×{c}" for t, c in sorted(v["tags"].items(), key=lambda x: -x[1])[:3])
            out.append(f"| {n} | {avg(v['good'])} | {avg(v['talk'])} | {avg(v['ai'])} | {len(v['good'])} | {v['best']} | "
                       f"{mm(line, n, 'exclaim_ratio')} | {mm(line, n, 'fragment_ratio')} | {mm(line, n, 'bare_imperative_ratio')} | {tags} |")
        out.append("")
    out += ["## 每个 brief", ""]
    for bid in sorted({b for b, _ in cell}):
        out += [f"### {bid}（{len(rated_by[bid])} 人评过）", "", "| 组合 | 质量 | 对人说话 | AI 感 | 备注 |", "|---|---|---|---|---|"]
        rows = [(n, c) for (b, n), c in cell.items() if b == bid]
        for n, c in sorted(rows, key=lambda x: -(sum(x[1]["good"]) / len(x[1]["good"]) if x[1]["good"] else 0)):
            out.append(f"| {n} | {avg(c['good'])} | {avg(c['talk'])} | {avg(c['ai'])} | {'；'.join(c['notes'])} |")
        out.append("")
    text = "\n".join(out)
    (run / "reveal.md").write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
