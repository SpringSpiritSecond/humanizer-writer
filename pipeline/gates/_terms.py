"""闸门共用：逐字查找、禁用词解析、brief 字段逐字检查。"""
from __future__ import annotations

import re

from ..briefs import resolve
from ..contract import hit
from ..textutil import normalize


def find_all(text: str, term: str) -> list[list[int]]:
    if not term:
        return []
    return [[m.start(), m.start() + len(term)] for m in re.finditer(re.escape(term), text)]


def expected(value: str, line: str | None = None) -> str:
    """brief 里的值和稿件走同一套统一格式再比，免得半角/全角标点造成误判。"""
    return normalize(value, None).strip()


def forbidden_terms(entries) -> list[tuple[str, str]]:
    """must_not 每一项可能是字面词（“竞品名”），也可能是说明（“‘最’‘第一’等极限词”）。

    有引号的只取引号里的词；没有引号的整项当字面词。返回 [(词, 原条目)]。
    """
    out = []
    for e in entries or []:
        if not isinstance(e, str) or not e.strip():
            continue
        quoted = re.findall(r"[“\"‘']([^”\"’']+)[”\"’']", e)
        for t in (quoted or [e.strip()]):
            out.append((expected(t), e))
    return out


def check_forbidden(text: str, entries, rule: str) -> list[dict]:
    hits = []
    for term, entry in forbidden_terms(entries):
        for span in find_all(text, term):
            # 单字禁用词（如“最”）误伤太多，只提示，交给 G1 的语境规则判断
            sev = "warn" if len(term) == 1 else "block"
            hits.append(hit(rule, f"出现了 brief 禁用的“{term}”（must_not：{entry}），删掉或换说法",
                            sev, span, term, field="must_not"))
    return hits


def check_exact(text: str, brief: dict, paths, rule: str, why: str) -> list[dict]:
    """paths 里每个字段的每个值都必须逐字出现在稿件里。缺了就在 hit 里写清字段和应有的值。"""
    hits = []
    for path in paths or []:
        for p, v, parent in resolve(brief, path):
            if isinstance(parent, dict) and parent.get("must_match") is False:
                continue
            if not isinstance(v, str) or not v.strip():
                continue
            want = expected(v)
            if want not in text:
                label = parent.get("field") if isinstance(parent, dict) and isinstance(parent.get("field"), str) else ""
                name = f"{p}（{label}）" if label else p
                hits.append(hit(rule, f"{why}：字段 {name} 应逐字出现“{want}”，稿件里找不到",
                                "block", None, want, field=p, expected=want))
    return hits
