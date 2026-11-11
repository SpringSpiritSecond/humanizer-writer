"""文本工具：统一格式、口播字数、数字抽取、分句。"""
from __future__ import annotations

import re

from workbench.normalize import normalize as _wb_normalize

CJK = "㐀-鿿豈-﫿"
_SPOKEN = re.compile(f"[{CJK}]|[A-Za-z]+|\\d")
_ACTION_LINE = re.compile(r"^（.*）$")
_SPEAKER = re.compile(r"^[^\s：（）“”]{1,12}：")


def normalize(text: str, line: str | None = None) -> str:
    """和工作台导入时同一套统一格式，保证 span 下标和工作台看到的一致。"""
    return _wb_normalize(text, line)


def spoken_chars(text: str, line: str) -> int:
    """要念出来的字数：汉字一个算一个，英文单词一个算一个，数字一位算一个。

    台词线去掉动作线“（……）”和行首的“角色名：”。
    """
    n = 0
    for row in text.split("\n"):
        row = row.strip()
        if line == "台词":
            if _ACTION_LINE.match(row):
                continue
            row = _SPEAKER.sub("", row, count=1)
            row = re.sub(r"（[^）]*）", "", row)      # 行内动作提示也不念
        n += len(_SPOKEN.findall(row))
    return n


def sentences(text: str) -> list[tuple[int, int]]:
    """按 。！？；换行 分句，返回 [起, 止) 下标。"""
    out, start = [], 0
    for m in re.finditer(r"[。！？!?；\n]", text):
        if m.end() > start:
            out.append((start, m.end()))
        start = m.end()
    if start < len(text):
        out.append((start, len(text)))
    return out


def sentence_of(text: str, pos: int) -> tuple[int, int]:
    for s, e in sentences(text):
        if s <= pos < e:
            return s, e
    return 0, len(text)


# ---- 数字 ----

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}
_CN_BIG = {"万": 10_000, "亿": 100_000_000}
# 中文数字后面跟这些量词才当数字，免得把“一起”“一下”“千万别”算进去
_MEASURE = ("元|块|毛|角|分钟|秒|小时|天|日|周|个月|月|年|岁|杯|瓶|盒|袋|包|件|个|只|次|遍|倍|折|斤|公斤|克|千克|毫升|升|"
            "米|厘米|公里|人|位|家|款|种|期|号|点|%|％")
_ARABIC = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_CHINESE = re.compile(f"[零〇一二两三四五六七八九十百千万亿]+(?=\\s*(?:{_MEASURE}))")


def cn2num(s: str) -> float | None:
    total, section, digit = 0, 0, None
    for ch in s:
        if ch in _CN_DIGIT:
            digit = digit * 10 + _CN_DIGIT[ch] if digit is not None else _CN_DIGIT[ch]   # “二〇二六”逐位读
        elif ch in _CN_UNIT:
            section += (digit if digit is not None else 1) * _CN_UNIT[ch]
            digit = None
        elif ch in _CN_BIG:
            section += digit or 0
            total += (section or 1) * _CN_BIG[ch]
            section, digit = 0, None
        else:
            return None
    return float(total + section + (digit or 0))


def numbers(text: str) -> list[dict]:
    """抽出文本里的数字：[{span, raw, value}]。中文数字只认后面跟量词的；单个“一”和“第 N”不算。"""
    out = []
    for m in _ARABIC.finditer(text):
        out.append({"span": [m.start(), m.end()], "raw": m.group(), "value": float(m.group().replace(",", ""))})
    for m in _CHINESE.finditer(text):
        raw = m.group()
        if raw == "一" or (m.start() > 0 and text[m.start() - 1] == "第"):
            continue
        v = cn2num(raw)
        if v is not None:
            out.append({"span": [m.start(), m.end()], "raw": raw, "value": v})
    out.sort(key=lambda d: d["span"][0])
    return out
