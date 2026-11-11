"""G1 合规：《广告法》第九条通用极限词，按 2023 年执法指南第六条做豁免分流。

只在 profile.compliance.enabled 为 true 时检查，否则直接放行（metrics.enabled=false）。

判定：
- 命中词典里的极限词，且不在排除语境（“最近”“第一集”）里 → block，verdict=fail；
- 命中词落在豁免区（同品牌自我比较、使用提示、依据标准的分级、型号或商标，或者就在 brief 的品牌词里）
  → 转复核（verdict=review），不直接拒；
- 其他“最+X”属于模糊区 → 转复核。

词典在 pipeline/data/广告法极限词.json；行业条款待法务补。配置参数 dictionary 可以换一份词典。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ..briefs import ROOT
from ..contract import hit, result
from ..textutil import sentence_of
from ._terms import expected, find_all

DEFAULT_DICT = Path(__file__).resolve().parents[1] / "data" / "广告法极限词.json"


@lru_cache(maxsize=8)
def load_dictionary(path: str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_DICT
    if not p.is_absolute():
        p = ROOT / p
    d = json.loads(p.read_text(encoding="utf-8"))
    for group in ("terms", "fuzzy", "exclusions", "exemptions"):
        for e in d.get(group, []):
            e["_re"] = re.compile(e["pattern"])
    return d


def _overlaps(a, b) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _exemption(text: str, span, d: dict, brand_spans) -> tuple[str, str] | None:
    for bs in brand_spans:
        if _overlaps(span, bs):
            return "model_or_trademark", "用语就在品牌名或商标里"
    s, e = sentence_of(text, span[0])
    sent = text[s:e]
    for ex in d.get("exemptions", []):
        if ex.get("scope") == "overlap":
            if any(_overlaps(span, (m.start(), m.end())) for m in ex["_re"].finditer(text)):
                return ex["id"], ex.get("basis", "")
        elif ex["_re"].search(sent):
            return ex["id"], ex.get("basis", "")
    return None


def check(text: str, brief: dict, d: dict) -> list[dict]:
    excluded = [(m.start(), m.end()) for ex in d.get("exclusions", []) for m in ex["_re"].finditer(text)]
    brand_spans = [tuple(s) for t in ((brief.get("must_include") or {}).get("brand_terms") or [])
                   if isinstance(t, str) for s in find_all(text, expected(t))]
    hits, taken = [], []

    def consider(m, entry, fuzzy: bool):
        span = (m.start(), m.end())
        if any(_overlaps(span, x) for x in excluded) or any(_overlaps(span, x) for x in taken):
            return
        taken.append(span)
        word = m.group()
        ex = _exemption(text, span, d, brand_spans)
        if ex:
            hits.append(hit("g1.exempt_zone", f"“{word}”可能属于豁免情形（{ex[1] or ex[0]}），转人工复核",
                            "warn", span, word, term_id=entry["id"], exemption=ex[0]))
        elif fuzzy:
            hits.append(hit("g1.fuzzy", f"“{text[span[0]:min(len(text), span[1] + 2)]}”可能是比较宣称，转人工复核",
                            "warn", span, word, term_id=entry["id"]))
        elif entry.get("severity", "block") == "block":
            hits.append(hit("g1.absolute_term", f"“{word}”属于《广告法》第九条的绝对化用语，删掉或换成可核实的具体信息",
                            "block", span, word, term_id=entry["id"]))
        else:
            hits.append(hit("g1.absolute_term", f"“{word}”需要复核", "warn", span, word, term_id=entry["id"]))

    for entry in d.get("terms", []):
        for m in entry["_re"].finditer(text):
            consider(m, entry, False)
    for entry in d.get("fuzzy", []):
        for m in entry["_re"].finditer(text):
            consider(m, entry, True)
    hits.sort(key=lambda h: h["span"][0])
    return hits


def run(ctx: dict) -> dict:
    comp = (ctx["profile"].get("compliance") or {})
    if not comp.get("enabled"):
        return result("G1", "hard", "pass", None, [], {"enabled": False})
    d = load_dictionary((ctx.get("config") or {}).get("dictionary"))
    hits = check(ctx["text"], ctx["brief"], d)
    industries = comp.get("industries") or []
    if industries:
        hits.append(hit("g1.industry_pending", f"行业条款待法务补，这些行业暂未检查：{'、'.join(industries)}", "hint"))
    if any(h["severity"] == "block" for h in hits):
        verdict, route = "fail", None
    elif any(h["rule"] in ("g1.exempt_zone", "g1.fuzzy") or h["severity"] == "warn" for h in hits):
        verdict, route = "review", "human"
    else:
        verdict, route = "pass", None
    return result("G1", "hard", verdict, route, hits,
                  {"enabled": True, "dictionary_version": d.get("version"),
                   "blocked": sum(h["severity"] == "block" for h in hits),
                   "review": sum(h["rule"] in ("g1.exempt_zone", "g1.fuzzy") for h in hits)})
