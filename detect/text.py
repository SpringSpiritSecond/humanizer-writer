"""文本切分、profile 读取和受保护片段。S2、G3 共用。

所有 span 都是原文（ctx["text"]）里 Python str 的下标，左闭右开。
为了不让台词行首的“角色名：”参与检测，切分在一份等长的“工作文本”上进行：
说话人前缀被替换成空格，下标与原文一一对应。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

RULES_PATH = Path(__file__).with_name("rules.json")

COUNTABLE = re.compile(r"[㐀-鿿豈-﫿A-Za-z0-9]")
CJK = re.compile(r"[㐀-鿿豈-﫿]")
# 句末：句号、叹号、问号、省略号，后面可以跟右引号或右括号
SENT_END = re.compile(r"(?:[。！？!?]+|…{1,}|\.{3,})[”’」』）)]*")
CLAUSE_SEP = re.compile(r"[，,、；;：:。！？!?…]+")
# 台词行首的说话人：“角色名：”或“角色名（动作）：”
SPEAKER = re.compile(r"[ \t　]*[^\s：:（()）]{1,10}(?:（[^）\n]*）|\([^)\n]*\))?[ \t　]*[：:]")
ACTION_ONLY = re.compile(r"\s*[（(][^\n]*[）)]\s*")
DASH = re.compile(r"[—―]+|-{2,}")


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def countable_len(s: str) -> int:
    return len(COUNTABLE.findall(s))


def rule_state(profile: dict | None, rule_id: str) -> str:
    state = ((profile or {}).get("rules") or {}).get(rule_id, "on")
    return state if state in ("on", "hint", "off") else "on"


def severity_for(state: str) -> str:
    return "hint" if state == "hint" else "warn"


def exception_ids(profile: dict | None) -> set[str]:
    out = set()
    for e in (profile or {}).get("exceptions") or []:
        out.add(e.get("id") if isinstance(e, dict) else str(e))
    return out


def excerpt(text: str, span: tuple[int, int], limit: int = 40) -> str:
    s = text[span[0]:span[1]].strip()
    return s if len(s) <= limit else s[:limit] + "…"


def _resolve(obj, path: list[str]):
    """按 'a.b[].c' 形式取值，返回字符串列表。"""
    if not path:
        if isinstance(obj, str):
            return [obj]
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, str)]
        return []
    head, rest = path[0], path[1:]
    many = head.endswith("[]")
    key = head[:-2] if many else head
    if not isinstance(obj, dict) or key not in obj:
        return []
    val = obj[key]
    if many:
        out = []
        for item in val if isinstance(val, list) else []:
            out.extend(_resolve(item, rest))
        return out
    return _resolve(val, rest)


def protected_strings(profile: dict | None, brief: dict | None) -> list[str]:
    """不检测的原文片段。

    - profile.fidelity.exact 里列的字段：G2 要求逐字一致，S3 改不了，标了也没用；
    - 例外 slogan_verbatim 生效时，brief.must_include.brand_terms 里的品牌词和 slogan。
    """
    brief = brief or {}
    out: list[str] = []
    for path in ((profile or {}).get("fidelity") or {}).get("exact") or []:
        out.extend(_resolve(brief, path.split(".")))
    if "slogan_verbatim" in exception_ids(profile):
        out.extend(_resolve(brief, ["must_include", "brand_terms"]))
    return sorted({s.strip() for s in out if s and s.strip()}, key=len, reverse=True)


class Doc:
    """一份稿件切好的结构。"""

    def __init__(self, text: str, line: str | None = None, profile: dict | None = None,
                 brief: dict | None = None):
        self.text = text or ""
        self.line = line or (profile or {}).get("line")
        self.profile = profile or {}
        self.exceptions = exception_ids(profile)
        self.is_dialogue = self.line == "台词"
        self.work = self._mask_speakers(self.text) if self.is_dialogue else self.text
        self.paragraphs = self._paragraphs()
        self.sentences = self._sentences()
        self.protected = self._protected_spans(protected_strings(profile, brief))

    # --- 切分 -------------------------------------------------------------
    def _mask_speakers(self, text: str) -> str:
        chars = list(text)
        pos = 0
        for raw in text.splitlines(keepends=True):
            m = SPEAKER.match(raw)
            if m:
                for i in range(pos, pos + m.end()):
                    chars[i] = " "
            pos += len(raw)
        return "".join(chars)

    def _paragraphs(self) -> list[tuple[int, int]]:
        """每个非空行算一段。台词里一行就是一个人的一次发言或一条动作线。"""
        out = []
        pos = 0
        for raw in self.work.splitlines(keepends=True):
            body = raw.rstrip("\r\n")
            stripped = body.strip()
            if stripped:
                start = pos + (len(body) - len(body.lstrip()))
                out.append((start, start + len(stripped)))
            pos += len(raw)
        return out

    def _sentences(self) -> list[tuple[int, int]]:
        out = []
        for ps, pe in self.paragraphs:
            cur = ps
            for m in SENT_END.finditer(self.work, ps, pe):
                out.extend(self._trim(cur, m.end()))
                cur = m.end()
            out.extend(self._trim(cur, pe))
        return out

    def _trim(self, s: int, e: int) -> list[tuple[int, int]]:
        seg = self.work[s:e]
        lead = len(seg) - len(seg.lstrip())
        trail = len(seg) - len(seg.rstrip())
        s2, e2 = s + lead, e - trail
        return [(s2, e2)] if e2 > s2 and countable_len(self.work[s2:e2]) else []

    def _protected_spans(self, strings: list[str]) -> list[tuple[int, int]]:
        spans = []
        for s in strings:
            start = 0
            while True:
                i = self.text.find(s, start)
                if i < 0:
                    break
                spans.append((i, i + len(s)))
                start = i + 1
        return spans

    # --- 查询 -------------------------------------------------------------
    def is_protected(self, span: tuple[int, int]) -> bool:
        return any(span[0] < pe and ps < span[1] for ps, pe in self.protected)

    def paragraph_index(self, pos: int) -> int:
        for i, (ps, pe) in enumerate(self.paragraphs):
            if ps <= pos < pe:
                return i
        return -1

    def sentence_at(self, pos: int) -> tuple[int, int] | None:
        for s, e in self.sentences:
            if s <= pos < e:
                return (s, e)
        return None

    def is_action(self, span: tuple[int, int]) -> bool:
        """整句都在括号里（动作线）。"""
        return bool(ACTION_ONLY.fullmatch(self.work[span[0]:span[1]]))

    def is_unfinished(self, span: tuple[int, int]) -> bool:
        tail = self.work[span[0]:span[1]].rstrip("”’」』）) ")
        return tail.endswith(("…", "——", "—", "--", "..."))

    def sentences_in(self, para: tuple[int, int]) -> list[tuple[int, int]]:
        return [s for s in self.sentences if para[0] <= s[0] < para[1]]

    def clauses(self, start: int, end: int) -> list[tuple[int, int, str]]:
        """按标点切成分句，返回 (起, 止, 结尾标点)。"""
        out = []
        cur = start
        for m in CLAUSE_SEP.finditer(self.work, start, end):
            if m.start() > cur:
                out.append((cur, m.start(), m.group()))
            cur = m.end()
        if cur < end:
            out.append((cur, end, ""))
        return out

    def dashes(self, honor_exception: bool = True) -> list[tuple[int, int]]:
        """破折号位置；台词 dash_interrupt 例外生效时去掉表示打断的那些。"""
        spec = load_rules()["s2"]["dash"]
        out = []
        for m in DASH.finditer(self.work):
            s, e = m.span()
            before = self.work[s - 1:s]
            after = self.work[e:e + 1]
            if before.isdigit() and after.isdigit():
                continue  # 数字范围
            if honor_exception and "dash_interrupt" in self.exceptions and self._is_interrupt(e, spec):
                continue
            out.append((s, e))
        return out

    def _is_interrupt(self, end: int, spec: dict) -> bool:
        line_end = self.work.find("\n", end)
        rest = self.work[end: line_end if line_end >= 0 else len(self.work)]
        rest = rest.lstrip("”’」』）) \t　")
        if not rest or rest[0] in "（(…":
            return True
        return any(rest.startswith(w) for w in spec["interrupt_followers"])
