"""S0 brief 校验：按两条线的 brief 模板（eval/briefs/<线>/_template.json）检查必填字段。

缺字段、字段还是模板里的占位文字、线不对，都退回 brief（verdict=fail）。
"""
from __future__ import annotations

import json

from ..briefs import TEMPLATES, raw, resolve
from ..contract import hit, result

# 每条线的必填字段。"list" 表示必须是非空列表，"text" 是非空字符串，"num" 是正数。
REQUIRED = {
    "口播": [
        ("id", "text"),
        ("facts", "list"),
        ("facts[].field", "text"),
        ("facts[].value", "text"),
        ("must_include.brand_terms", "list"),
        ("must_include.cta", "text"),
        ("audience", "text"),
        ("speaker", "text"),
        ("target.duration_sec", "num"),
    ],
    "台词": [
        ("id", "text"),
        ("scene_card.location_time", "text"),
        ("scene_card.characters", "list"),
        ("scene_card.characters[].name", "text"),
        ("scene_card.scene_goal", "text"),
        ("scene_card.conflict", "text"),
        ("scene_card.beats", "list"),
        ("target.duration_sec", "num"),
    ],
}
# 缺了只提示、不退回的字段
OPTIONAL = {
    "口播": ["must_not", "source.rights"],
    "台词": ["scene_card.previously", "locked.lines", "locked.props_and_names", "source.rights"],
}


def _template_strings(line: str) -> set[str]:
    try:
        tpl = json.loads(TEMPLATES[line].read_text(encoding="utf-8"))
    except (OSError, KeyError, ValueError):
        return set()
    out: set[str] = set()

    def walk(v):
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                # facts[].field 在模板里是真实可用的字段名（如“价格”），不算占位
                if k not in ("id", "line", "field"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(tpl)
    return out


def _check(value, kind: str) -> bool:
    if kind == "list":
        return isinstance(value, list) and len(value) > 0
    if kind == "text":
        return isinstance(value, str) and value.strip() != ""
    if kind == "num":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
    return value is not None


def check_brief(brief: dict, line: str) -> list[dict]:
    hits = []
    if not isinstance(brief, dict):
        return [hit("s0.not_object", "brief 应是 JSON 对象")]
    if brief.get("line") != line:
        hits.append(hit("s0.line_mismatch", f"brief.line 是 {brief.get('line')!r}，这份配置跑的是 {line}"))
        return hits
    placeholders = _template_strings(line)
    for path, kind in REQUIRED[line]:
        if kind == "list":
            if not _check(raw(brief, path), "list"):
                hits.append(hit("s0.missing", f"缺必填字段 {path}（应是非空列表）", field=path))
            continue
        found = resolve(brief, path)
        if not found:
            hits.append(hit("s0.missing", f"缺必填字段 {path}", field=path))
            continue
        for p, v, _ in found:
            if not _check(v, kind):
                hits.append(hit("s0.missing", f"必填字段 {p} 为空或类型不对", field=p))
            elif isinstance(v, str) and v in placeholders:
                hits.append(hit("s0.placeholder", f"{p} 还是模板里的占位文字：{v}", field=p, excerpt=v))
    for path in OPTIONAL[line]:
        if not resolve(brief, path):
            hits.append(hit("s0.optional_missing", f"建议填写 {path}", severity="warn", field=path))
    return hits


_STYLE_FILE = __import__("pathlib").Path(__file__).resolve().parents[1] / "data" / "风格指令.json"


def style_directives(brief: dict) -> list[dict]:
    """brief 里的风格指令（“要短”“制造紧张感”……）只提示，不退回。和线无关，任何文体都适用。

    这些词会被模型照字面执行（“短”写成“断”）。brief 只写场景：谁、对谁、为什么开口、想达到什么。
    """
    try:
        phrases = json.loads(_STYLE_FILE.read_text(encoding="utf-8"))["phrases"]
    except (OSError, KeyError, ValueError):
        return []
    found: dict[str, str] = {}

    def walk(v, path):
        if isinstance(v, str):
            for p in sorted(phrases, key=len, reverse=True):   # 长的先匹配：有“不煽情”就不再单报“煽情”
                if p in v and p not in found and not any(p in q for q in found):
                    found[p] = path
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("source", "id", "line", "status") and not k.startswith("_"):
                    walk(x, f"{path}.{k}" if path else k)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")

    walk(brief, "")
    return [hit("s0.style_directive",
                f"{path} 里有风格指令“{p}”：brief 只写场景（谁、对谁、为什么开口、想达到什么），风格交给 skill 和评测",
                severity="warn", field=path, excerpt=p) for p, path in found.items()]


def run(ctx: dict) -> dict:
    hits = check_brief(ctx["brief"], ctx["line"]) + style_directives(ctx["brief"])
    blocking = [h for h in hits if h["severity"] == "block"]
    return result("S0", "hard", "fail" if blocking else "pass", None, hits,
                  {"missing": len(blocking), "warnings": len(hits) - len(blocking)})
