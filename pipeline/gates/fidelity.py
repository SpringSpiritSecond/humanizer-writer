"""G2 保真：事实、锁定内容、承诺；新增细节也算。

- profile.fidelity.exact 列的字段，值要逐字出现（facts[] 里 must_match 为 false 的跳过）；
- profile.fidelity.forbidden 指向的禁用词（口播线是 must_not）不能出现；
- 口播线（no_new_numbers / no_new_claims）：稿件里不能有 brief 里没有的数字和承诺（“保证”“包退”“X 天见效”）；
- 台词线：锁定台词、人名、道具都写在 exact 里；beat 是否保住先占位，只记录，
  配置参数 beat_checker（点分路径，签名 (ctx, beats) -> list[hit]）以后接 LLM 比对。

有问题时 verdict=route、route_to=S3，hits 里写清是哪个字段（hit.field）不一致。
轮数用完由 runner 转人工。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ..briefs import corpus, raw
from ..contract import hit, result
from ..textutil import normalize, numbers
from ._terms import check_exact, check_forbidden

PROMISES = Path(__file__).resolve().parents[1] / "data" / "承诺词.json"


@lru_cache(maxsize=1)
def _promise_patterns():
    d = json.loads(PROMISES.read_text(encoding="utf-8"))
    return [(p["id"], re.compile(p["pattern"])) for p in d["patterns"]]


def new_numbers(text: str, brief: dict) -> list[dict]:
    src = normalize(corpus(brief))
    allowed = {n["value"] for n in numbers(src)}
    hits = []
    for n in numbers(text):
        if n["value"] not in allowed:
            hits.append(hit("g2.new_number", f"brief 里没有“{n['raw']}”这个数字；删掉，或改回 brief 里的写法",
                            "block", n["span"], n["raw"]))
    return hits


def new_claims(text: str, brief: dict) -> list[dict]:
    src = normalize(corpus(brief))
    hits = []
    for pid, rx in _promise_patterns():
        for m in rx.finditer(text):
            if m.group() in src:
                continue
            hits.append(hit("g2.new_claim", f"“{m.group()}”是 brief 里没有的承诺，删掉",
                            "block", [m.start(), m.end()], m.group(), claim_id=pid))
    return hits


def _load_callable(path: str):
    import importlib
    mod, _, attr = path.partition(":")
    return getattr(importlib.import_module(mod), attr or "run")


def check_beats(ctx: dict) -> tuple[list[dict], dict]:
    beats_path = (ctx["profile"].get("fidelity") or {}).get("beats")
    beats = raw(ctx["brief"], beats_path) if beats_path else None
    if not beats:
        return [], {"checked": False, "count": 0}
    checker = (ctx.get("config") or {}).get("beat_checker")
    if not checker:
        return [], {"checked": False, "count": len(beats), "field": beats_path,
                    "note": "beat 是否保住还没有自动比对，只记录；以后在配置 G2.params.beat_checker 接 LLM 比对"}
    fn = checker if callable(checker) else _load_callable(checker)
    hits = list(fn(ctx, beats) or [])
    return hits, {"checked": True, "count": len(beats), "field": beats_path, "lost": len(hits)}


def run(ctx: dict) -> dict:
    text, brief, line = ctx["text"], ctx["brief"], ctx["line"]
    fid = ctx["profile"].get("fidelity") or {}
    hits = check_exact(text, brief, fid.get("exact"), "g2.exact_missing", "字段不一致")
    forbidden = fid.get("forbidden")
    if forbidden:
        hits += [h for h in check_forbidden(text, raw(brief, forbidden), "g2.forbidden") if h["severity"] == "block"]
    if fid.get("no_new_numbers"):
        hits += new_numbers(text, brief)
    if fid.get("no_new_claims"):
        hits += new_claims(text, brief)
    beat_hits, beat_metrics = check_beats(ctx)
    hits += beat_hits
    blocking = [h for h in hits if h["severity"] == "block"]
    fields = sorted({h.get("field") for h in blocking if h.get("field")})
    metrics = {"problems": len(blocking), "fields": fields, "beats": beat_metrics}
    if blocking:
        return result("G2", "hard", "route", "S3", hits, metrics)
    return result("G2", "hard", "pass", None, hits, metrics)
