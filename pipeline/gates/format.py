"""G0 格式：长度或时长、必含的品牌词和 CTA、锁定台词、禁用词（must_not）。

不过就淘汰这一份（verdict=fail）。

时长按“要念出来的字数 ÷ 语速”估。语速优先用 brief.target.chars_per_min，其次 profile.length.chars_per_min；
两处都没填（profile 里是 null）时，用配置参数 default_chars_per_min 估一个值，并给出 warn，不算失败。

配置参数（ctx["config"]）：
    default_chars_per_min  语速没填时的估计值，默认 240 字/分钟
"""
from __future__ import annotations

from ..briefs import get
from ..contract import hit, result
from ..textutil import spoken_chars
from ._terms import check_exact, check_forbidden

DEFAULT_CPM = 240


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    if isinstance(v, str):
        try:
            f = float(v.strip())
            return f if f > 0 else None
        except ValueError:
            return None
    return None


def check_length(ctx: dict) -> tuple[list[dict], dict]:
    text, line, brief, profile = ctx["text"], ctx["line"], ctx["brief"], ctx["profile"]
    spec = profile.get("length") or {}
    unit = spec.get("unit", "sec")
    tol = float(spec.get("tolerance", 0.2))
    target = _num(get(brief, spec.get("source") or "target.duration_sec"))
    chars = spoken_chars(text, line)
    metrics = {"spoken_chars": chars, "unit": unit, "tolerance": tol, "target": target}
    hits = []
    if target is None:
        hits.append(hit("g0.length_target_missing", f"brief 里没有可用的目标长度（{spec.get('source')}），跳过长度检查", "warn"))
        return hits, metrics
    if unit == "chars":
        actual = float(chars)
    else:
        cpm = _num(get(brief, "target.chars_per_min"))
        cpm_from = "brief"
        if cpm is None:
            cpm, cpm_from = _num(spec.get("chars_per_min")), "profile"
        if cpm is None:
            cpm, cpm_from = float((ctx.get("config") or {}).get("default_chars_per_min", DEFAULT_CPM)), "estimate"
            hits.append(hit("g0.chars_per_min_estimated",
                            f"brief 和 profile 都没填语速，按 {cpm:g} 字/分钟估算时长；请按自家配音实测后填进 brief.target.chars_per_min",
                            "warn"))
        actual = chars / cpm * 60
        metrics.update({"chars_per_min": cpm, "chars_per_min_from": cpm_from})
    metrics["actual"] = round(actual, 1)
    lo, hi = target * (1 - tol), target * (1 + tol)
    metrics["allowed"] = [round(lo, 1), round(hi, 1)]
    if not lo <= actual <= hi:
        what = "字数" if unit == "chars" else "估算时长"
        u = "字" if unit == "chars" else " 秒"
        direction = "超长" if actual > hi else "太短"
        hits.append(hit("g0.length", f"{what} {actual:.0f}{u}，目标 {target:g}{u} ±{tol:.0%}（{lo:.0f}–{hi:.0f}），{direction}",
                        "block"))
    return hits, metrics


def run(ctx: dict) -> dict:
    text, line, brief = ctx["text"], ctx["line"], ctx["brief"]
    hits, metrics = check_length(ctx)
    if line == "口播":
        hits += check_exact(text, brief, ["must_include.brand_terms", "must_include.cta"], "g0.must_include", "缺必含词")
    if line == "台词":
        hits += check_exact(text, brief, ["locked.lines"], "g0.locked_line", "锁定台词被改动或删掉")
    hits += check_forbidden(text, brief.get("must_not"), "g0.must_not")
    blocking = [h for h in hits if h["severity"] == "block"]
    metrics["blocking"] = len(blocking)
    return result("G0", "hard", "fail" if blocking else "pass", None, hits, metrics)
