"""S2 规则检测：只报告命中位置，交给 S3 定向改写。

规则数据在 rules.json 的 "s2" 下；每条规则的 kind 对应本文件里一个小函数。
函数只负责找候选位置；两档触发（单次即标 / 同段 ≥2 才标）、profile 开关、
受保护片段和通用例外在 run() 里统一处理。
"""
from __future__ import annotations

import re
from functools import lru_cache

from .text import (Doc, countable_len, excerpt, load_rules, rule_state, severity_for)

Span = tuple[int, int]

CONCRETE = re.compile(
    r"\d|%|％|[一二两三四五六七八九十百千万半]+(?:个|元|块|克|斤|公斤|小时|分钟|秒|天|年|次|倍|毫升|升|米|厘米|毫米|寸|瓦|档|种|款)")
QUESTION_END = re.compile(r"[？?][”’」』）)]*$")
SENTENCE_STOP = re.compile(r"[。！？!?…]")


@lru_cache(maxsize=None)
def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern)


def _regex_in(doc: Doc, spans: list[Span], patterns: list[str], anchor: bool = False) -> list[Span]:
    out = []
    for s, e in spans:
        sub = doc.work[s:e]
        for p in patterns:
            pat = _compile(p)
            if anchor:
                m = pat.match(sub)
                if m and m.end() > m.start():
                    out.append((s + m.start(), s + m.end()))
            else:
                out.extend((s + m.start(), s + m.end()) for m in pat.finditer(sub) if m.end() > m.start())
    return out


def _closing_sentences(doc: Doc, n: int) -> list[Span]:
    sents = [x for x in doc.sentences if not doc.is_action(x)]
    tail = sents[-n:] if n else []
    if "unfinished_line" in doc.exceptions:
        tail = [x for x in tail if not doc.is_unfinished(x)]
    return tail


def find_regex(doc: Doc, spec: dict) -> list[Span]:
    scope = spec.get("scope", "any")
    if scope == "paragraph_first_sentence":
        spans = [ss[0] for ss in (doc.sentences_in(p) for p in doc.paragraphs) if ss]
    elif scope == "text_last_sentences":
        spans = _closing_sentences(doc, int(spec.get("last_n", 1)))
    else:
        spans = doc.paragraphs
    return _regex_in(doc, spans, spec["patterns"], bool(spec.get("anchor")))


def _repeat_ok(doc: Doc) -> bool:
    """口头禅、短句重复例外：一模一样的重复不算排比。"""
    return bool({"catchphrase_repeat", "short_repeat"} & doc.exceptions)


def _items_identical(doc: Doc, items: list[tuple[int, int, str]]) -> bool:
    return len({doc.work[s:e].strip() for s, e, _ in items}) == 1


def find_triple_parallel(doc: Doc, spec: dict) -> list[Span]:
    out = []
    prefixes = sorted(spec["anaphora"], key=len, reverse=True)
    max_len = int(spec.get("max_item_chars", 12))
    min_run = int(spec.get("min_run", 3))
    concrete_ok = "spoken_triple" in doc.exceptions
    pronouns = tuple(spec.get("pronouns", []))
    min_shared = int(spec.get("min_shared_prefix", 2))

    def body(c):
        return doc.work[c[0]:c[1]].strip()

    def run_prefix(a: str, b: str, sep: str) -> str | None:
        """两个相邻分句共用的开头：要么是词表里的排比开头，要么是不以代词起头的 ≥2 字共同前缀。"""
        listed = next((p for p in prefixes if a.startswith(p) and b.startswith(p)
                       and len(a) > len(p) and len(b) > len(p)), None)
        if listed:
            return listed
        k = 0
        while k < min(len(a), len(b)) and a[k] == b[k]:
            k += 1
        # 顿号隔开的共同前缀多半是名词罗列（红烧肉、红烧鱼），不算
        if k >= min_shared and not a.startswith(pronouns) and "、" not in sep:
            return a[:k]
        return None

    for ps, pe in doc.paragraphs:
        cl = doc.clauses(ps, pe)
        i = 0
        while i < len(cl):
            a = body(cl[i])
            prefix = None
            j = i + 1
            if j < len(cl) and countable_len(a) <= max_len:
                prefix = run_prefix(a, body(cl[j]), cl[i][2])
            if prefix:
                while j < len(cl):
                    b = body(cl[j])
                    if not (b.startswith(prefix) and countable_len(b) <= max_len):
                        break
                    j += 1
            run = cl[i:j]
            if prefix and len(run) >= min_run:
                i = j
                if _repeat_ok(doc) and _items_identical(doc, run):
                    continue
                if concrete_ok and sum(bool(CONCRETE.search(doc.work[s:e])) for s, e, _ in run) >= 2:
                    continue
                if "unfinished_line" in doc.exceptions and any(c in run[-1][2] for c in "…—"):
                    continue
                out.append((run[0][0], run[-1][1]))
            else:
                i += 1
    for s, e in _regex_in(doc, doc.paragraphs, spec.get("patterns", [])):
        if concrete_ok and len(CONCRETE.findall(doc.work[s:e])) >= 2:
            continue
        out.append((s, e))
    return out


def find_four_char_parallel(doc: Doc, spec: dict) -> list[Span]:
    out = []
    min_run = int(spec.get("min_run", 3))

    def is_four(c):
        b = doc.work[c[0]:c[1]].strip()
        return len(b) == 4 and countable_len(b) == 4 and not re.search(r"[0-9A-Za-z]", b)

    for ps, pe in doc.paragraphs:
        cl = doc.clauses(ps, pe)
        i = 0
        while i < len(cl):
            j = i
            while j < len(cl) and is_four(cl[j]):
                j += 1
                if SENTENCE_STOP.search(cl[j - 1][2]):
                    break  # 排比不跨句
            run = cl[i:j]
            if len(run) >= min_run and not (_repeat_ok(doc) and _items_identical(doc, run)):
                out.append((run[0][0], run[-1][1]))
            i = max(j, i + 1)
    return out


def find_de_stacking(doc: Doc, spec: dict) -> list[Span]:
    out = []
    need = int(spec.get("min_de_per_clause", 3))
    compounds = spec.get("not_particle", [])
    for ps, pe in doc.paragraphs:
        for s, e, _ in doc.clauses(ps, pe):
            n = 0
            for k in range(s, e):
                if doc.work[k] != "的":
                    continue
                if any(doc.work[k - w.index("的"): k - w.index("的") + len(w)] == w for w in compounds):
                    continue
                n += 1
            if n >= need:
                out.append((s, e))
    return out


def find_bei_stack(doc: Doc, spec: dict) -> list[Span]:
    out = []
    compounds = spec.get("not_passive", [])
    for ps, pe in doc.paragraphs:
        for s, e, _ in doc.clauses(ps, pe):
            for k in range(s, e):
                if doc.work[k] == "被" and doc.work[k:k + 2] not in compounds:
                    out.append((k, e))
    return out


def find_dash(doc: Doc, spec: dict) -> list[Span]:
    return doc.dashes(honor_exception=True)


def find_rhetorical_question(doc: Doc, spec: dict) -> list[Span]:
    out = []
    audience = spec.get("audience_words", [])
    spoken_ok = "spoken_rhetorical_question" in doc.exceptions
    for para in doc.paragraphs:
        sents = doc.sentences_in(para)
        for a, b in zip(sents, sents[1:]):
            q = doc.work[a[0]:a[1]]
            if not QUESTION_END.search(q):
                continue
            if QUESTION_END.search(doc.work[b[0]:b[1]]):
                continue  # 连问不是自问自答
            if spoken_ok and any(w in q for w in audience):
                continue
            out.append(a)
    return out


FINDERS = {
    "regex": find_regex,
    "triple_parallel": find_triple_parallel,
    "four_char_parallel": find_four_char_parallel,
    "de_stacking": find_de_stacking,
    "bei_stack": find_bei_stack,
    "dash": find_dash,
    "rhetorical_question": find_rhetorical_question,
}


def detect(doc: Doc, rules: dict | None = None) -> tuple[list[dict], dict]:
    rules = rules or load_rules()["s2"]
    hits: list[dict] = []
    off: list[str] = []
    for rule_id, spec in rules.items():
        state = rule_state(doc.profile, rule_id)
        if state == "off":
            off.append(rule_id)
            continue
        spans = sorted(set(FINDERS[spec["kind"]](doc, spec)))
        spans = [sp for sp in spans if not doc.is_protected(sp)]
        if "short_fragment" in doc.exceptions:
            spans = [sp for sp in spans if not _in_short_fragment(doc, sp)]
        if spec.get("tier") == "paragraph":
            spans = _paragraph_tier(doc, spans, int(spec.get("min_count", 2)))
        for sp in spans:
            hits.append({
                "rule": rule_id,
                "span": [sp[0], sp[1]],
                "excerpt": excerpt(doc.text, sp),
                "severity": severity_for(state),
                "message": spec["message"],
            })
    hits.sort(key=lambda h: (h["span"][0], h["span"][1], h["rule"]))
    return hits, {"rules_off": off}


def _in_short_fragment(doc: Doc, sp: Span) -> bool:
    sent = doc.sentence_at(sp[0])
    return bool(sent) and countable_len(doc.work[sent[0]:sent[1]]) <= 4


def _paragraph_tier(doc: Doc, spans: list[Span], need: int) -> list[Span]:
    by_para: dict[int, list[Span]] = {}
    for sp in spans:
        by_para.setdefault(doc.paragraph_index(sp[0]), []).append(sp)
    return sorted(sp for group in by_para.values() if len(group) >= need for sp in group)


def run(ctx: dict) -> dict:
    doc = Doc(ctx.get("text", ""), ctx.get("line"), ctx.get("profile"), ctx.get("brief"))
    hits, extra = detect(doc)
    counts: dict[str, int] = {}
    for h in hits:
        counts[h["rule"]] = counts.get(h["rule"], 0) + 1
    return {
        "stage": "S2",
        "kind": "report",
        "verdict": "pass",
        "route_to": None,
        "hits": hits,
        "metrics": {"hit_counts": counts, **extra, "protected_spans": len(doc.protected)},
    }
