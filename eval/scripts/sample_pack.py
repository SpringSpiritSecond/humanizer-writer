"""按参赛组合表批量写稿（只写稿、不改稿），产出盲审用的数据。

    python eval/scripts/sample_pack.py --arms eval/arms/bbtt-sample.json \
        --briefs eval/briefs/bbtt --out eval/out/bbtt-r1

产出（都在 --out 下）：
    results.json   每份稿子的完整记录：参赛组合、模型、skill、token、S2 命中、G3 指标（揭盲用，审稿时别打开）
    blind.json     审稿页用：只有不透明编号和文本，每个 brief 下顺序打乱
    key.json       不透明编号 → 参赛组合（揭盲用）
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import random
import secrets
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from detect.stages import g3, s2  # noqa: E402
from pipeline.adapters.base import resolve_skill  # noqa: E402
from pipeline.adapters.openai_compat import AdapterError, OpenAICompatAdapter  # noqa: E402
from pipeline.textutil import normalize  # noqa: E402

PROFILE = {"台词": "profiles/台词.json", "科普": "profiles/口播.json", "口播": "profiles/口播.json",
           "训练": "profiles/训练.json"}
NORM_LINE = {"台词": "台词", "科普": "口播", "口播": "口播", "训练": "口播"}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def one(arm: dict, cfg: dict, brief: dict) -> dict:
    m = cfg["models"][arm["model"]]
    params = {**cfg["defaults"], "api_key_env": m["api_key_env"]}
    slots = {"A": {"skills": [resolve_skill(s) for s in arm["skills"]], "combine": "serial"}}
    ad = OpenAICompatAdapter("generator", m["model"], m["vendor"], params, slots)
    line = brief["line"]
    rec = {"arm": arm["id"], "model": m["model"], "skills": arm["skills"], "brief_id": brief["id"], "line": line}
    t0 = time.monotonic()
    try:
        text = ad.generate({"line": line, "brief": brief}, 1)[0]
    except (AdapterError, Exception) as e:  # noqa: BLE001
        rec.update(error=f"{type(e).__name__}: {e}", seconds=round(time.monotonic() - t0, 1))
        return rec
    text = normalize(text, NORM_LINE[line])
    profile = load(ROOT / PROFILE[line])
    ctx = {"line": NORM_LINE[line], "brief": brief, "profile": profile, "text": text, "round": 0,
           "history": [], "config": {}}
    rec.update(text=text, chars=len(text), seconds=round(time.monotonic() - t0, 1),
               usage=ad.describe()["usage"],
               s2_hits=[{k: h.get(k) for k in ("rule", "excerpt", "severity")} for h in s2(ctx)["hits"]],
               g3_metrics=g3(ctx)["metrics"])
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", required=True)
    ap.add_argument("--briefs", required=True, help="下面按 <线>/*.json 放 brief")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only-line", default=None)
    ap.add_argument("--resume", action="store_true", help="保留 results.json 里已成功的，只补跑缺的和失败的")
    a = ap.parse_args()

    cfg = load(a.arms)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for line, arms in cfg["arms"].items():
        if a.only_line and line != a.only_line:
            continue
        for arm in arms:
            # 参赛组合可以用另一版 brief（"briefs": "<目录>"），用来比较 brief 写法本身的影响
            for bf in sorted((Path(arm.get("briefs") or a.briefs) / line).glob("*.json")):
                jobs.append((arm, load(bf)))
    results = []
    prev = out / "results.json"
    if a.resume and prev.exists():
        results = [r for r in load(prev) if r.get("text")]
        have = {(r["arm"], r["brief_id"]) for r in results}
        jobs = [(arm, b) for arm, b in jobs if (arm["id"], b["id"]) not in have]
        print(f"续跑：已有 {len(results)} 份成功，补跑 {len(jobs)} 份")
    print(f"共 {len(jobs)} 份，{a.workers} 路并发")
    total = len(results) + len(jobs)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(one, arm, cfg, brief): (arm["id"], brief["id"]) for arm, brief in jobs}
        for f in cf.as_completed(futs):
            r = f.result()
            results.append(r)
            flag = "错误：" + r["error"][:80] if r.get("error") else f"{r['chars']} 字，{r['seconds']}s"
            print(f"  [{len(results)}/{total}] {r['brief_id']} · {r['arm']} → {flag}", flush=True)

    rng = random.Random(secrets.randbits(64))
    key, blind = {}, {"briefs": []}
    briefs = {}
    for r in results:
        briefs.setdefault(r["brief_id"], []).append(r)
    for bid in sorted(briefs):
        rows = [r for r in briefs[bid] if r.get("text")]
        rng.shuffle(rows)
        brief = load(next((Path(a.briefs)).glob(f"*/{bid}.json")))
        pub = {k: v for k, v in brief.items() if k not in ("source", "status", "fictional", "is_example")}
        items = []
        for r in rows:
            # 续跑时保留已有编号，已经打过的分不会对不上
            vid = r.get("vid") or secrets.token_hex(4)
            r["vid"] = vid
            key[vid] = {"arm": r["arm"], "model": r["model"], "skills": r["skills"]}
            items.append({"vid": vid, "text": r["text"]})
        blind["briefs"].append({"id": bid, "line": rows[0]["line"] if rows else brief["line"], "brief": pub, "items": items})

    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "blind.json").write_text(json.dumps(blind, ensure_ascii=False, indent=1), encoding="utf-8")
    errs = [r for r in results if r.get("error")]
    tok_in = sum((r.get("usage") or {}).get("prompt_tokens") or 0 for r in results)
    tok_out = sum((r.get("usage") or {}).get("completion_tokens") or 0 for r in results)
    print(f"完成：{len(results) - len(errs)} 份成功，{len(errs)} 份失败；输入 {tok_in} token，输出 {tok_out} token")


if __name__ == "__main__":
    main()
