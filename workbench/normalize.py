"""展示前的统一格式。

格式本身就会泄露来源（AI 爱用 Markdown、半角标点、整齐的列表），所以导入时就把
所有版本规整成同一种样子，评审只看到规整后的 display_text。
"""
from __future__ import annotations

import re

CJK = r"㐀-鿿豈-﫿"
_CJK_CHAR = re.compile(f"[{CJK}]")

_HALF_TO_FULL = {",": "，", "?": "？", "!": "！", ":": "：", ";": "；", "(": "（", ")": "）"}


def strip_markdown(text: str) -> str:
    text = re.sub(r"```[^\n]*\n?", "", text)                     # 代码块围栏
    text = re.sub(r"`([^`]*)`", r"\1", text)                       # 行内代码
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)          # 图片
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)           # 链接
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)               # 标题
        line = re.sub(r"^\s{0,3}>\s?", "", line)                    # 引用
        line = re.sub(r"^\s*(?:[-*+]|\d+[.、)）])\s+", "", line)     # 列表
        if re.fullmatch(r"\s*(?:[-*_]\s*){3,}", line):              # 分隔线
            continue
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)                 # 粗体
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)  # 斜体
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    return text


def _has_cjk_near(s: str, i: int) -> bool:
    left = s[i - 1] if i > 0 else ""
    right = s[i + 1] if i + 1 < len(s) else ""
    return bool(_CJK_CHAR.match(left) or _CJK_CHAR.match(right) or
                left in "”」）" or right in "“「（")


def unify_punct(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("　", " ")
    text = re.sub(r"\.{3,}|。{3,}|…+", "……", text)                  # 省略号
    text = re.sub(r"—+|--+|－－", "——", text)                       # 破折号
    text = re.sub(r"(?<=[^\s\d])~", "～", text)
    # 弯/直引号统一成中文弯引号，按出现顺序配对
    out, open_q = [], True
    for ch in text:
        if ch in "\"“”":
            out.append("“" if open_q else "”")
            open_q = not open_q
        else:
            out.append(ch)
    text = "".join(out)
    text = text.replace("「", "“").replace("」", "”").replace("『", "‘").replace("』", "’")
    # 中文语境里的半角标点 → 全角；数字里的逗号冒号（1,000 / 10:30）不动
    chars = list(text)
    for i, ch in enumerate(chars):
        if ch in _HALF_TO_FULL and _has_cjk_near(text, i):
            prev, nxt = text[i - 1:i], text[i + 1:i + 2]
            if ch in ",:" and prev.isdigit() and nxt.isdigit():
                continue
            chars[i] = _HALF_TO_FULL[ch]
        elif ch == "." and i > 0 and _CJK_CHAR.match(text[i - 1]) and (i + 1 == len(text) or text[i + 1] in " \n"):
            chars[i] = "。"
    text = "".join(chars)
    # 全角标点前后的空格去掉；中英文之间的空格保留原样
    text = re.sub(r"[ \t]*([，。？！：；、（）“”……——])[ \t]*", r"\1", text)
    return text


def normalize_script_line(line: str) -> str:
    """台词统一成“角色名：台词”和“（动作线）”。"""
    s = line.strip()
    m = re.match(r"^\[(.+)\]$|^【(.+)】$|^\((.+)\)$|^（(.+)）$", s)
    if m:
        return "（" + next(g for g in m.groups() if g) + "）"
    m = re.match(r"^([^\s：:（）()“”]{1,12})\s*[：:]\s*(.+)$", s)
    if m:
        return f"{m.group(1)}：{m.group(2).strip()}"
    return s


def normalize(text: str, line: str | None = None) -> str:
    text = strip_markdown(text)
    text = unify_punct(text)
    rows = [re.sub(r"[ \t]+", " ", r).strip() for r in text.split("\n")]
    if line == "台词":
        rows = [normalize_script_line(r) if r else r for r in rows]
    text = "\n".join(rows)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text
