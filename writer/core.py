"""写稿工作流：检查 brief → 写 N 份 → 逐份检查 → 出报告，由人挑。

依据四轮盲审（2026-11-12 至 11-13，见 docs/工作流-当前推荐.md）：
- 最有效的是 brief 的写法：只写场景和事实，不写风格要求，不能出现的内容不给写稿模型看；
- 模型用 Gemini 4 Argon；skill 用 scene-anchored；不自动改稿。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from detect.stages import g3, s2
from detect.trace import annotate
from pipeline.adapters.base import resolve_skill
from pipeline.adapters.openai_compat import OpenAICompatAdapter, _public_brief
from pipeline.gates.brief import style_directives
from pipeline.textutil import normalize

ROOT = Path(__file__).resolve().parents[1]
PROFILES = {"台词": "profiles/台词.json", "训练": "profiles/训练.json", "口播": "profiles/口播.json"}
NUM = re.compile(r"\d+(?:\.\d+)?%?")
CLOCK_MIN = re.compile(r"(?<=\d)[:：]\d{2}")   # 9:00 里的 :00 只是写法不同，不算新数字
CJK = re.compile(r"[一-鿿]")

EXTRA_PROMPT = (
    "下面是写稿依据的材料，和照着它写出来的一篇稿子。逐句对照，找出稿子里材料没有提供的事实、安排、承诺、"
    "已经做过的事、时间、地点、人物或数字，也包括把材料里的说法说得更具体（例如材料写“周四”，稿子写成“本周四”或具体日期）。\n"
    "这些不算多出来的：对材料的同义改写或换算；按常识给对方的提醒和建议（例如提前储水）；礼貌用语。\n"
    "只输出 JSON 数组，每项是 {\"句子\": 稿子原句, \"多出来的\": 材料里没有的那部分}；没有就输出 []。")


def _nums(s: str) -> set[str]:
    return set(NUM.findall(CLOCK_MIN.sub("", s)))


def _strings(v) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return []


# ---------------- brief ----------------

def check_brief(brief: dict) -> dict:
    """必填项缺了就退回；风格要求、强调只提示。"""
    errors, warnings = [], []
    for k in ("id", "line"):
        if not str(brief.get(k) or "").strip():
            errors.append(f"缺 {k}")
    if not (brief.get("speaker") or brief.get("scene_card")):
        errors.append("缺 speaker：写清谁在说、对谁说、在什么场合、两人是什么关系（台词可以用 scene_card）")
    if not (brief.get("facts") or brief.get("scene_card") or brief.get("topic")):
        errors.append("缺要讲的内容：facts（或台词的 scene_card）")
    tpl = json.loads((ROOT / "writer/brief_template.json").read_text(encoding="utf-8"))
    placeholders = set(_strings({k: v for k, v in tpl.items() if not k.startswith("_") and k != "id"}))
    for s in _strings({k: v for k, v in brief.items() if not k.startswith("_")}):
        if s in placeholders:
            errors.append(f"还是模板里的占位文字：{s[:30]}")
    for h in style_directives(brief):
        warnings.append(h["message"])
    if brief.get("must_not") and not brief.get("check_only"):
        warnings.append("must_not 不会给写稿模型看，写完才检查；以后请写在 check_only 里")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


# ---------------- 写稿 ----------------

def make_adapter(cfg: dict, with_skills: bool = True) -> OpenAICompatAdapter:
    m = cfg["model"]
    params = {k: v for k, v in m.items() if k not in ("name", "vendor")}
    slot = {"skills": [resolve_skill(s) for s in cfg.get("skills", [])] if with_skills else [], "combine": "serial"}
    return OpenAICompatAdapter("generator", m["name"], m.get("vendor", ""), params, {"A": slot})


def write(brief: dict, cfg: dict, n: int, adapter=None) -> tuple[list[str], dict]:
    ad = adapter or make_adapter(cfg)
    texts = ad.generate({"line": brief["line"], "brief": brief}, n)
    return texts, ad.describe().get("usage") or {}


# ---------------- 检查 ----------------

def _profile(line: str) -> tuple[str, dict]:
    known = PROFILES.get(line, "profiles/口播.json")
    p = json.loads((ROOT / known).read_text(encoding="utf-8"))
    return ("台词" if line == "台词" else "口播"), p


def find_extra(text: str, brief: dict, checker) -> list[dict] | None:
    """用模型对照 brief，找稿子里多出来的事实、安排和承诺。规则检查拦不住这类问题：
    新人试用时，一份停水通知编了“已在门厅张贴纸质通知”“帮忙提水”，规则检查却报“没有发现问题”。
    返回 None 表示没检查（没有模型，或模型出错）。"""
    if checker is None:
        return None
    material = json.dumps(_public_brief(brief), ensure_ascii=False, indent=1)
    msgs = [{"role": "system", "content": EXTRA_PROMPT},
            {"role": "user", "content": f"材料：\n{material}\n\n稿子：\n{text}"}]
    try:
        out = checker._chat(msgs, "extra-check")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        return None
    try:
        items = json.loads(m.group(0))
    except ValueError:
        return None
    return [i for i in items if isinstance(i, dict) and i.get("多出来的")]


def check_draft(text: str, brief: dict, cfg: dict, checker=None) -> dict:
    """结论三档：不过（写了不能出现的说法，或事实里的数字没写对）、待确认（有 brief 里没有的内容）、通过。
    其余问题只作提示。checker 是用来对照 brief 的模型；为 None 时跳过“多出来的内容”检查。"""
    norm_line, profile = _profile(brief["line"])
    text = normalize(text, norm_line)
    fails, flags = [], []

    tr = annotate(text, brief)
    if tr["prompt_trace"]:
        fails.append("出现了不能出现的说法：" + "、".join(f"{k}×{v}" for k, v in tr["prompt_trace_terms"].items()))

    fact_text = " ".join(_strings(brief.get("facts")))
    brief_text = " ".join(_strings(_public_brief(brief)))
    for num in sorted(_nums(fact_text)):
        if num not in text:
            fails.append(f"事实里的数字 {num} 没写进稿子（或写法不一样）")
    extra = sorted(_nums(text) - _nums(brief_text))
    if extra and brief["line"] != "训练":
        flags.append("brief 里没有的数字：" + "、".join(extra) + "（是换算还是编的？）")

    target = (brief.get("target") or {}).get("chars")
    chars = len(CJK.findall(text))
    if isinstance(target, (int, float)) and target > 0:
        tol = cfg.get("chars_tolerance", 0.3)
        if abs(chars - target) > target * tol:
            flags.append(f"长度 {chars} 字，目标 {target} 字")

    if tr["brief_echo_max"]:
        flags.append("brief 里的词被反复说：" + "、".join(f"{k}×{v}" for k, v in tr["brief_echo_terms"].items()))
    if (tr.get("colloquial_per_kchar") or 0) >= 3:
        flags.append(f"口语化标记偏多（{tr['colloquial_per_kchar']}‰）：看看和说话人的身份、场合合不合")

    ctx = {"line": norm_line, "brief": brief, "profile": profile, "text": text, "round": 0, "history": [], "config": {}}
    m = g3(ctx)["metrics"]
    if (m.get("exclaim_ratio") or 0) >= 0.3:
        flags.append(f"感叹句偏多（{m['exclaim_ratio']:.0%}）：情绪靠内容带，不靠标点")
    if (m.get("fragment_ratio") or 0) >= 0.3:
        flags.append(f"碎句偏多（{m['fragment_ratio']:.0%}）")
    if (m.get("bare_imperative_ratio") or 0) >= 0.15:
        flags.append(f"没头没尾的口令偏多（{m['bare_imperative_ratio']:.0%}）")
    hits = [h for h in s2(ctx)["hits"] if h["severity"] != "hint"]
    for h in hits[:6]:
        flags.append(f"句式：{h['rule']}「{h.get('excerpt', '')[:24]}」")

    extra_items = find_extra(text, brief, checker)
    status = "不过" if fails else ("待确认" if extra_items else "通过")
    return {"text": text, "chars": chars, "pass": not fails, "status": status, "fails": fails, "flags": flags,
            "extra": extra_items or [], "extra_checked": extra_items is not None,
            "metrics": {**{k: tr[k] for k in ("prompt_trace", "brief_echo_max", "colloquial_per_kchar")},
                        **{k: m.get(k) for k in ("exclaim_ratio", "fragment_ratio", "bare_imperative_ratio")}}}


# ---------------- 跑一份 brief ----------------

def run(brief_path: Path, out_dir: Path, cfg: dict, n: int | None = None, adapter=None, checker="auto") -> dict:
    brief = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    bc = check_brief(brief)
    report = {"brief": str(brief_path), "brief_check": bc, "config": {"model": cfg["model"]["name"], "skills": cfg.get("skills", [])},
              "drafts": [], "created": time.strftime("%Y-%m-%d %H:%M")}
    if not bc["ok"]:
        _write_report(out_dir, brief, report)
        return report
    texts, usage = write(brief, cfg, n or cfg.get("n", 3), adapter=adapter)
    report["usage"] = usage
    if checker == "auto":
        checker = make_adapter(cfg, with_skills=False) if cfg.get("extra_check", True) else None
    for i, t in enumerate(texts, 1):
        c = check_draft(t, brief, cfg, checker=checker)
        (out_dir / f"稿{i}.txt").write_text(c["text"] + "\n", encoding="utf-8")
        report["drafts"].append({"no": i, **c})
    _write_report(out_dir, brief, report)
    return report


def _write_report(out_dir: Path, brief: dict, report: dict):
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# {brief.get('id', '')}（{brief.get('line', '')}）", "",
         f"模型 {report['config']['model']}，skill {', '.join(report['config']['skills']) or '无'}，{report['created']}", ""]
    bc = report["brief_check"]
    if bc["errors"]:
        L += ["## brief 退回", ""] + [f"- {e}" for e in bc["errors"]] + [""]
    if bc["warnings"]:
        L += ["## brief 提示", ""] + [f"- {w}" for w in bc["warnings"]] + [""]
    if report["drafts"]:
        L += ["## 稿子", "",
              "结论分三档：**不过**＝写了不能出现的说法，或事实里的数字不对；**待确认**＝有 brief 里没有的内容，"
              "确认属实再用；**通过**＝没查出硬问题。写得好不好检查不出来，挑哪份由人定。", ""]
        for d in report["drafts"]:
            L.append(f"### 稿{d['no']}：{d['status']}（{d['chars']} 字）")
            L += [f"- 不过：{x}" for x in d["fails"]]
            L += [f"- 待确认：“{e.get('多出来的', '')}”（{e.get('句子', '')}）——brief 里没有" for e in d.get("extra", [])]
            if not d.get("extra_checked"):
                L.append("- 没做“多出来的内容”检查（没有可用的模型），请自己对照 brief 看一遍")
            L += [f"- 提示：{x}" for x in d["flags"]] or ["- 提示：无"]
            L += ["", "```", d["text"], "```", ""]
    (out_dir / "report.md").write_text("\n".join(L), encoding="utf-8")
