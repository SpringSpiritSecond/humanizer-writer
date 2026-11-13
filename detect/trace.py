"""通用检查：句子回应的是场景，还是提示词和套路（第三轮盲审后加）。

三项，都不依赖文体，只记录、不打回：

- prompt_trace：brief 里只用来检查的约束（check_only、must_not）中的说法，在稿子里出现了几次。
  写稿模型看不到这些内容，所以只要出现，就说明是自己编出来的，或者是 brief 别处漏出来的。
- brief_echo：brief 里描述场景的词（情况、画面提示、背景、说话人）在稿子里被重复的次数，
  只报出重复 4 次以上的词。这是“brief 强调什么，稿子就反复说什么”。
- colloquial_per_kchar：口语化标记的密度（咱们、啥、呗……）。这项没有统一的好坏标准，
  用来比较：同一场景下加 skill 后是否明显更口语，或与同类场景相比高出很多。
- template_ratio（批量）：同一组合在不同 brief 下写出几乎一样的句子，这类句子的占比。
  这些句子不随场景变化，就是模板句。
"""
from __future__ import annotations

import re
from collections import Counter

CJK = re.compile(r"[一-鿿]")
SENT = re.compile(r"[^。！？!?\n]+[。！？!?]?")
COLLOQUIAL = re.compile(r"咱们|咱[^们]|啥|呗|嘛(?=[。！？，\s]|$)|瞎|甭|俺|贼(?=[好多快])|整明白|磨出来|琢磨")


def _strings(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return []


def _phrases(s: str) -> list[str]:
    """把一条约束拆成可检测的说法：引号里的词，或者整条去掉“不/不能/不要”后的核心词（≥2 字）。"""
    quoted = re.findall(r"[“\"「]([^”\"」]{2,12})[”\"」]", s)
    if quoted:
        return quoted
    core = re.sub(r"^(不能|不要|不得|不|别|禁止)(用|说|提|写|出现)?", "", s.strip())
    core = re.split(r"[，,；;（(、或]", core)[0].strip()
    return [core] if 2 <= len(core) <= 12 else []


def prompt_trace(text: str, brief: dict) -> dict:
    items = _strings(brief.get("check_only")) + _strings(brief.get("must_not"))
    found = {}
    for s in items:
        for p in _phrases(s):
            n = text.count(p)
            if n:
                found[p] = n
    return {"prompt_trace": sum(found.values()), "prompt_trace_terms": found}


def _anchors(brief: dict) -> str:
    """本来就该在稿子里反复出现的东西：要讲的事实、主题、人名、道具、锁定内容。brief 回声不算这些。"""
    sc = brief.get("scene_card") or {}
    names = [c.get("name", "") for c in sc.get("characters", []) if isinstance(c, dict)]
    return " ".join(_strings([brief.get("facts"), brief.get("topic"), brief.get("locked"), names,
                              brief.get("must_include")]))


def brief_echo(text: str, brief: dict, min_count: int = 4) -> dict:
    """brief 里描述情况、提醒、背景的词在稿子里被重复的次数（第三轮：“对面”每份出现 1–6 次）。
    第四轮发现台词里“星图”“梯梯”这些人名道具被误报，所以 _anchors 里的词不算。"""
    src = " ".join(_strings({k: brief.get(k) for k in ("situation", "screen_cues", "context", "speaker")}))
    anchors = _anchors(brief)
    grams = {src[i:i + n] for n in (2, 3) for i in range(len(src) - n + 1)
             if all(CJK.match(c) for c in src[i:i + n]) and src[i:i + n] not in anchors}
    counts = {g: text.count(g) for g in grams}
    rep = {g: c for g, c in counts.items() if c >= min_count}
    # 去掉被更长重复词包含的短词
    rep = {g: c for g, c in rep.items() if not any(g != h and g in h and rep[h] >= c for h in rep)}
    return {"brief_echo_max": max(rep.values()) if rep else 0, "brief_echo_terms": dict(sorted(rep.items(), key=lambda x: -x[1])[:5])}


def colloquial(text: str) -> dict:
    chars = len(CJK.findall(text))
    n = len(COLLOQUIAL.findall(text))
    return {"colloquial": n, "colloquial_per_kchar": round(n / chars * 1000, 2) if chars else None}


def _bigrams(s: str) -> set[str]:
    s = "".join(CJK.findall(s))
    return {s[i:i + 2] for i in range(len(s) - 1)}


def template_ratio(texts_by_brief: dict[str, str], threshold: float = 0.6, min_chars: int = 6) -> dict[str, float | None]:
    """同一组合在不同 brief 下的稿子：一句话在别的 brief 的稿子里有几乎一样的句子，就算模板句。返回每个 brief 的模板句占比。"""
    sents = {b: [s for s in SENT.findall(t) if len(CJK.findall(s)) >= min_chars] for b, t in texts_by_brief.items()}
    grams = {b: [_bigrams(s) for s in ss] for b, ss in sents.items()}
    out = {}
    for b, gs in grams.items():
        if not gs:
            out[b] = None
            continue
        others = [g for o, og in grams.items() if o != b for g in og]
        hit = sum(1 for g in gs if any(len(g & h) / max(1, len(g | h)) >= threshold for h in others))
        out[b] = round(hit / len(gs), 3) if others else None
    return out


def annotate(text: str, brief: dict) -> dict:
    return {**prompt_trace(text, brief), **brief_echo(text, brief), **colloquial(text)}
