"""按点分路径取 brief 里的字段，以及 brief 里能当“出处”的文本。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {"台词": ROOT / "eval" / "briefs" / "台词" / "_template.json",
             "口播": ROOT / "eval" / "briefs" / "口播" / "_template.json"}

# 这些字段不算稿件内容的出处：管理字段、目标时长、禁用词本身
NON_CONTENT_KEYS = {"id", "line", "source", "target", "must_not", "is_example", "notes_admin", "_说明"}


def resolve(obj, path: str) -> list[tuple[str, object, object]]:
    """resolve(brief, "facts[].value") → [(具体路径, 值, 所在 dict), ...]。

    路径可以带 "brief." 前缀；末端是 list 时展开成每一项。找不到就返回空列表。
    """
    if path.startswith("brief."):
        path = path[len("brief."):]
    found = [("", obj, None)]
    for part in path.split("."):
        is_list = part.endswith("[]")
        key = part[:-2] if is_list else part
        nxt = []
        for p, cur, _ in found:
            if not isinstance(cur, dict) or key not in cur:
                continue
            base = f"{p}.{key}" if p else key
            val = cur[key]
            if is_list:
                if isinstance(val, list):
                    nxt.extend((f"{base}[{i}]", v, val) for i, v in enumerate(val))
            else:
                nxt.append((base, val, cur))
        found = nxt
    out = []
    for p, v, parent in found:
        if isinstance(v, list):
            out.extend((f"{p}[{i}]", x, parent) for i, x in enumerate(v))
        else:
            out.append((p, v, parent))
    return out


def raw(obj, path: str, default=None):
    """不展开列表，按 a.b.c 直接取原值。"""
    if path.startswith("brief."):
        path = path[len("brief."):]
    cur = obj
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def get(obj, path: str, default=None):
    r = resolve(obj, path)
    return r[0][1] if r else default


def corpus(brief: dict) -> str:
    """brief 里所有内容字段的文本拼在一起，用来判断稿件里的数字、承诺有没有出处。"""
    parts: list[str] = []

    def walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            parts.append(str(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for k, v in brief.items():
        if k not in NON_CONTENT_KEYS:
            walk(v)
    return "\n".join(parts)
