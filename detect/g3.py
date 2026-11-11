"""G3 风格计量：只算密度和分布，阈值从 ctx["config"]["thresholds"] 读。

没给阈值时 verdict 一律 pass，只记录 metrics（校准前不打回）。
给了阈值时：超标且规则在 profile 里是 "on"，返回 route → S3 并附命中位置；
规则是 "hint" 时只附 hint 级命中、不打回；"off" 时不检查这项阈值。
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter

from .text import COUNTABLE, Doc, countable_len, excerpt, load_rules, rule_state, severity_for

# 指标名 → 规则 id。批次内多样性对应 batch_diversity：distinct 越低、BLEU 越高越雷同。
METRIC_RULE = {
    "heading_per_kchar": "heading_density",
    "connector_per_kchar": "connector_density",
    "buzzword_per_kchar": "buzzword",
    "semicolon_per_kchar": "semicolon_dunhao",
    "dunhao_per_kchar": "semicolon_dunhao",
    "dash_per_kchar": "dash",
    "colon_per_kchar": "colon_conclusion",
    "sentence_len_cv": "uniform_length",
    "paragraph_len_cv": "uniform_length",
    "char_mattr": "synonym_rotation",
    "bigram_mattr": "synonym_rotation",
    "batch_distinct_2": "batch_diversity",
    "batch_distinct_3": "batch_diversity",
    "batch_self_bleu": "batch_diversity",
    "batch_bleu_current": "batch_diversity",
}
BATCH_METRICS = ("batch_distinct_2", "batch_distinct_3", "batch_self_bleu", "batch_bleu_current")

HEADING_MARK = re.compile(
    r"(?:#{1,6}\s*|[一二三四五六七八九十]+[、.．]|\d{1,2}[、.．)）]\s*|第[一二三四五六七八九十\d]+[部分章节点步][：:、\s]|【[^】]{1,15}】)")
ANY_PUNCT = re.compile(r"[。！？!?，,、；;：:…]")
CLAUSE_START = re.compile(r"(?:^|(?<=[\s，,。！？!?；;：:、”」』）)]))")


def _units(s: str) -> list[str]:
    return COUNTABLE.findall(s)


# --- 位置类指标 -------------------------------------------------------------
def heading_spans(doc: Doc) -> list[tuple[int, int]]:
    out = []
    paras = doc.paragraphs
    for i, (s, e) in enumerate(paras):
        if doc.is_dialogue and doc.work[s:e] != doc.text[s:e]:
            continue  # 有说话人前缀的行不是标题
        body = doc.text[s:e]
        if HEADING_MARK.match(body):
            out.append((s, e))
            continue
        if i + 1 < len(paras) and countable_len(body) <= 15 and not ANY_PUNCT.search(body) \
                and not doc.is_action((s, e)):
            nxt = doc.text[paras[i + 1][0]:paras[i + 1][1]]
            if countable_len(nxt) > 2 * countable_len(body):
                out.append((s, e))
    return out


def word_spans(doc: Doc, words: list[str], clause_start: bool = False) -> list[tuple[int, int]]:
    out = []
    for w in sorted(words, key=len, reverse=True):
        for m in re.finditer(re.escape(w), doc.work):
            sp = m.span()
            if clause_start and not CLAUSE_START.match(doc.work, sp[0]):
                continue
            if any(sp[0] < e and s < sp[1] for s, e in out):
                continue  # 长词优先，如“总而言之”不再算“总之”
            out.append(sp)
    return sorted(sp for sp in out if not doc.is_protected(sp))


def char_spans(doc: Doc, chars: str) -> list[tuple[int, int]]:
    return [(i, i + 1) for i, c in enumerate(doc.work) if c in chars and not doc.is_protected((i, i + 1))]


# --- 分布类指标 -------------------------------------------------------------
def cv(values: list[int]) -> float | None:
    if not values or statistics.mean(values) == 0:
        return None
    return round(statistics.pstdev(values) / statistics.mean(values), 4)


def mattr(tokens: list, window: int) -> float | None:
    if len(tokens) < window:
        return None
    counts = Counter(tokens[:window])
    total = len(counts)
    for i in range(window, len(tokens)):
        counts[tokens[i]] += 1
        old = tokens[i - window]
        counts[old] -= 1
        if counts[old] == 0:
            del counts[old]
        total += len(counts)
    return round(total / ((len(tokens) - window + 1) * window), 4)


def ngrams(units: list[str], n: int) -> list[str]:
    return ["".join(units[i:i + n]) for i in range(len(units) - n + 1)]


def bleu(hyp: list[str], refs: list[list[str]], max_n: int = 4) -> float:
    """字级 BLEU-4，n>1 时加一平滑，简短惩罚取最接近的参考长度。"""
    if not hyp or not refs:
        return 0.0
    log_p = 0.0
    for n in range(1, max_n + 1):
        h = Counter(ngrams(hyp, n))
        total = sum(h.values())
        max_ref: Counter = Counter()
        for r in refs:
            for g, c in Counter(ngrams(r, n)).items():
                max_ref[g] = max(max_ref[g], c)
        clipped = sum(min(c, max_ref[g]) for g, c in h.items())
        if n == 1:
            if clipped == 0:
                return 0.0
            p = clipped / total
        else:
            p = (clipped + 1) / (total + 1)
        log_p += math.log(p) / max_n
    ref_len = min((abs(len(r) - len(hyp)), len(r)) for r in refs)[1]
    bp = 1.0 if len(hyp) > ref_len else math.exp(1 - ref_len / len(hyp))
    return bp * math.exp(log_p)


def _batch_texts(ctx: dict) -> list[str]:
    out = []
    for b in ctx.get("batch_texts") or []:
        t = b.get("text") if isinstance(b, dict) else b
        if isinstance(t, str):
            out.append(t)
    return out


def batch_metrics(text: str, others: list[str], min_chars: int) -> dict:
    seqs = [_units(t) for t in [text] + others]
    seqs = [s for s in seqs if len(s) >= min_chars]
    if len(seqs) < 2 or len(_units(text)) < min_chars:
        return {"batch_size": len(seqs), "batch_distinct_2": None, "batch_distinct_3": None,
                "batch_self_bleu": None, "batch_bleu_current": None}
    out = {"batch_size": len(seqs)}
    for n in (2, 3):
        grams = [g for s in seqs for g in ngrams(s, n)]
        out[f"batch_distinct_{n}"] = round(len(set(grams)) / len(grams), 4) if grams else None
    scores = [bleu(s, seqs[:i] + seqs[i + 1:]) for i, s in enumerate(seqs)]
    out["batch_self_bleu"] = round(sum(scores) / len(scores), 4)
    out["batch_bleu_current"] = round(scores[0], 4)
    return out


def _uniform_run(doc: Doc, spans: list[tuple[int, int]]) -> tuple[int, int]:
    """找长度最接近的一串连续句（或段），作为“过匀”的命中位置；找不到就给全文。"""
    best = (0, 0)
    start = 0
    lens = [countable_len(doc.work[s:e]) for s, e in spans]
    for i in range(1, len(lens) + 1):
        if i == len(lens) or abs(lens[i] - lens[i - 1]) > max(2, 0.2 * lens[i - 1]):
            if i - start >= 3 and i - start > best[1] - best[0]:
                best = (start, i)
            start = i
    if best[1] - best[0] >= 3:
        return (spans[best[0]][0], spans[best[1] - 1][1])
    return (0, len(doc.text))


def compute(doc: Doc, ctx: dict) -> tuple[dict, dict]:
    """返回 (metrics, 每个指标的命中位置)。"""
    cfg = load_rules()["g3"]
    chars = countable_len(doc.work)
    kchar = chars / 1000 if chars else 0

    def per_k(n):
        return round(n / kchar, 2) if kchar else None

    sent = [s for s in doc.sentences if not doc.is_action(s)]
    paras = [p for p in doc.paragraphs if not doc.is_action(p)]
    positions = {
        "heading_per_kchar": heading_spans(doc),
        "connector_per_kchar": word_spans(doc, cfg["connectors"], clause_start=True),
        "buzzword_per_kchar": word_spans(doc, cfg["buzzwords"]),
        "semicolon_per_kchar": char_spans(doc, "；;"),
        "dunhao_per_kchar": char_spans(doc, "、"),
        "dash_per_kchar": [d for d in doc.dashes(honor_exception=True) if not doc.is_protected(d)],
        "colon_per_kchar": char_spans(doc, "：:"),
    }
    m: dict = {"chars": chars, "sentences": len(sent), "paragraphs": len(paras)}
    for name, spans in positions.items():
        m[name] = per_k(len(spans))

    s_len = [countable_len(doc.work[s:e]) for s, e in sent]
    p_len = [countable_len(doc.work[s:e]) for s, e in paras]
    m["sentence_len_cv"] = cv(s_len) if len(s_len) >= cfg["min_sentences_for_cv"] else None
    m["paragraph_len_cv"] = cv(p_len) if len(p_len) >= cfg["min_paragraphs_for_cv"] else None
    positions["sentence_len_cv"] = [_uniform_run(doc, sent)] if m["sentence_len_cv"] is not None else []
    positions["paragraph_len_cv"] = [_uniform_run(doc, paras)] if m["paragraph_len_cv"] is not None else []

    units = _units(doc.work)
    enough = len(units) >= cfg["min_chars_for_diversity"]
    w = cfg["mattr_window"]
    m["char_mattr"] = mattr(units, w) if enough else None
    m["bigram_mattr"] = mattr(ngrams(units, 2), w) if enough else None
    positions["char_mattr"] = positions["bigram_mattr"] = [(0, len(doc.text))]
    for name in BATCH_METRICS:
        positions[name] = [(0, len(doc.text))]  # 雷同是整份稿的问题，给全文

    m.update(batch_metrics(doc.work, [_mask(t, ctx, doc) for t in _batch_texts(ctx)],
                           cfg["min_chars_for_batch"]))
    return m, positions


def _mask(text: str, ctx: dict, doc: Doc) -> str:
    return Doc(text, doc.line, ctx.get("profile")).work if doc.is_dialogue else text


def _bound(spec) -> tuple[str, float] | None:
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return ("max", float(spec))
    if isinstance(spec, dict):
        if "max" in spec:
            return ("max", float(spec["max"]))
        if "min" in spec:
            return ("min", float(spec["min"]))
    return None


def run(ctx: dict) -> dict:
    doc = Doc(ctx.get("text", ""), ctx.get("line"), ctx.get("profile"), ctx.get("brief"))
    metrics, positions = compute(doc, ctx)
    thresholds = (ctx.get("config") or {}).get("thresholds") or {}
    messages = load_rules()["g3"]["messages"]
    hits: list[dict] = []
    exceeded: list[str] = []
    skipped: list[str] = []
    route = False
    for name, spec in thresholds.items():
        rule_id = METRIC_RULE.get(name)
        bound = _bound(spec)
        value = metrics.get(name)
        if rule_id is None or bound is None:
            skipped.append(name)
            continue
        state = rule_state(doc.profile, rule_id)
        if state == "off" or value is None:
            skipped.append(name)
            continue
        kind, limit = bound
        if (kind == "max" and value <= limit) or (kind == "min" and value >= limit):
            continue
        exceeded.append(name)
        route = route or state == "on"
        word = "上限" if kind == "max" else "下限"
        msg = f"{name}={value}，{word} {limit:g}。{messages[rule_id]}"
        for sp in positions.get(name) or [(0, len(doc.text))]:
            hits.append({"rule": rule_id, "span": [sp[0], sp[1]], "excerpt": excerpt(doc.text, sp),
                         "severity": severity_for(state), "message": msg})
    hits.sort(key=lambda h: (h["span"][0], h["rule"]))
    metrics["exceeded"] = exceeded
    if skipped:
        metrics["skipped_thresholds"] = skipped
    return {
        "stage": "G3",
        "kind": "soft",
        "verdict": "route" if route else "pass",
        "route_to": "S3" if route else None,
        "hits": hits,
        "metrics": metrics,
    }
