"""导出（管理员用，带揭盲信息）：CSV、JSONL、prompt/chosen/rejected 偏好格式。"""
from __future__ import annotations

import csv
import io
import json
import sqlite3

_SIDE_COLS = ["variant_id", "source_type", "source_label", "skill_git_hash", "model", "params", "sample_idx"]


def _source(conn, vid):
    if vid is None:
        return {k: None for k in _SIDE_COLS} | {"text": None}
    r = conn.execute("SELECT v.id, v.display_text, s.* FROM variant v JOIN variant_source s ON s.variant_id=v.id "
                     "WHERE v.id=?", (vid,)).fetchone()
    return {"variant_id": r["id"], "source_type": r["source_type"], "source_label": r["source_label"],
            "skill_git_hash": r["skill_git_hash"], "model": r["model"], "params": r["params_json"],
            "sample_idx": r["sample_idx"], "text": r["display_text"]}


def records(conn: sqlite3.Connection, with_text: bool = False) -> list[dict]:
    rows = conn.execute(
        "SELECT j.*, t.public_id, t.batch_id, t.kind, t.item_id, i.line, i.is_example, t.control_type, t.is_gold, "
        "t.gold_expected, t.display_order, t.swapped, t.left_variant_id, t.right_variant_id, "
        "rt.public_id AS repeat_of_public, t.is_repeat_of, r.name AS rater_name, r.is_simulated "
        "FROM judgment j JOIN task t ON t.id=j.task_id JOIN item i ON i.id=t.item_id "
        "JOIN rater r ON r.id=j.rater_id LEFT JOIN task rt ON rt.id=t.is_repeat_of ORDER BY j.id").fetchall()
    out = []
    cache: dict = {}
    for r in rows:
        def src(vid):
            if vid not in cache:
                cache[vid] = _source(conn, vid)
            return cache[vid]
        a, b = src(r["left_variant_id"]), src(r["right_variant_id"])
        tags = json.loads(r["tags_json"])
        pref = r["preference"]
        preferred = a["source_label"] if pref == "A" else b["source_label"] if pref == "B" else pref
        rec = {
            "judgment_id": r["id"], "task_id": r["public_id"], "task_db_id": r["task_id"], "batch_id": r["batch_id"],
            "rater_id": r["rater_id"], "rater_name": r["rater_name"], "rater_simulated": bool(r["is_simulated"]),
            "line": r["line"], "item_id": r["item_id"], "item_is_example": bool(r["is_example"]),
            "kind": r["kind"], "control_type": r["control_type"], "is_gold": bool(r["is_gold"]),
            "gold_expected": r["gold_expected"],
            "gold_correct": (pref == r["gold_expected"]) if r["is_gold"] else None,
            "is_repeat_of": r["repeat_of_public"], "is_repeat_of_db_id": r["is_repeat_of"],
            "display_order": r["display_order"], "swapped": bool(r["swapped"]),
            "ai_conf_a": r["ai_conf_a"], "ai_conf_b": r["ai_conf_b"], "preference": pref,
            "preferred_source": preferred,
            "tags_a": tags.get("A", []), "tags_b": tags.get("B", []),
            "spans": json.loads(r["spans_json"]), "reason": r["reason"],
            "duration_ms": r["duration_ms"], "too_fast": bool(r["too_fast"]), "revisions": r["revisions"],
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        }
        for side, s in (("a", a), ("b", b)):
            for k in _SIDE_COLS:
                rec[f"{side}_{k}"] = s[k]
            if with_text:
                rec[f"{side}_text"] = s["text"]
        out.append(rec)
    return out


def to_jsonl(conn) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records(conn, with_text=True))


def to_csv(conn) -> str:
    recs = records(conn, with_text=False)
    buf = io.StringIO()
    if not recs:
        return ""
    w = csv.DictWriter(buf, fieldnames=list(recs[0].keys()))
    w.writeheader()
    for r in recs:
        r = dict(r)
        for k in ("tags_a", "tags_b"):
            r[k] = "|".join(r[k])
        r["spans"] = json.dumps(r["spans"], ensure_ascii=False)
        w.writerow(r)
    return "﻿" + buf.getvalue()   # 带 BOM，Excel 直接打开不乱码


def render_prompt(line: str, public: dict) -> str:
    """把 brief 的公开部分写成生成用的提示，偏好数据里的 prompt 字段。"""
    if line == "台词":
        sc = public.get("scene_card", {})
        parts = [f"写一场戏的对白和动作线。前情：{sc.get('previously', '')}",
                 f"地点时间：{sc.get('location_time', '')}"]
        for c in sc.get("characters", []):
            parts.append(f"人物 {c.get('name')}：{c.get('profile', '')}；想要：{c.get('want', '')}")
        parts += [f"这场戏要完成：{sc.get('scene_goal', '')}", f"冲突：{sc.get('conflict', '')}",
                  "beat：" + " / ".join(sc.get("beats", []))]
        locked = public.get("locked", {})
        if locked.get("lines"):
            parts.append("必须原样保留：" + " / ".join(locked["lines"]))
        if locked.get("props_and_names"):
            parts.append("必须出现：" + "、".join(locked["props_and_names"]))
        tgt = public.get("target", {})
        parts.append(f"时长约 {tgt.get('duration_sec', '')} 秒；格式：{tgt.get('format', '')}")
    else:
        parts = ["写一条口播稿。"]
        for f in public.get("facts", []):
            parts.append(f"{f.get('field')}：{f.get('value')}" + ("（逐字一致）" if f.get("must_match") else ""))
        mi = public.get("must_include", {})
        if mi.get("brand_terms"):
            parts.append("必须出现：" + "、".join(mi["brand_terms"]))
        if mi.get("cta"):
            parts.append(f"CTA：{mi['cta']}")
        if public.get("must_not"):
            parts.append("不能出现：" + "、".join(public["must_not"]))
        parts += [f"受众：{public.get('audience', '')}", f"讲话人：{public.get('speaker', '')}",
                  f"目标时长：{public.get('target', {}).get('duration_sec', '')} 秒"]
    return "\n".join(parts)


def to_preference_jsonl(conn, include_simulated: bool = False, include_too_fast: bool = False) -> str:
    lines = []
    publics = {r["id"]: (r["line"], json.loads(r["public_json"]))
               for r in conn.execute("SELECT id, line, public_json FROM item")}
    for r in records(conn, with_text=True):
        if r["kind"] != "pairwise_pref" or r["preference"] not in ("A", "B"):
            continue
        if r["control_type"] in ("gold", "repeat"):
            continue
        if (r["rater_simulated"] and not include_simulated) or (r["too_fast"] and not include_too_fast):
            continue
        win, lose = ("a", "b") if r["preference"] == "A" else ("b", "a")
        line, public = publics[r["item_id"]]
        lines.append(json.dumps({
            "prompt": render_prompt(line, public),
            "chosen": r[f"{win}_text"], "rejected": r[f"{lose}_text"],
            "meta": {"item_id": r["item_id"], "line": line, "rater_id": r["rater_id"], "task_id": r["task_id"],
                     "chosen_source": r[f"{win}_source_label"], "rejected_source": r[f"{lose}_source_label"],
                     "ai_conf_chosen": r[f"ai_conf_{win}"], "ai_conf_rejected": r[f"ai_conf_{lose}"],
                     "item_is_example": r["item_is_example"], "rater_simulated": r["rater_simulated"]},
        }, ensure_ascii=False))
    return "".join(l + "\n" for l in lines)
