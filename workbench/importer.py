"""导入 brief（item）和候选稿（variant）。

JSON 格式：
    {"items": [<brief>, ...], "variants": [<variant>, ...]}
其中 brief 就是 eval/briefs/*/_template.json 的结构（必须有 id 和 line），
variant 字段：
    item_id, text, source_type, [candidate_id], [skill_git_hash], [model],
    [params]（对象或 JSON 字符串）, [sample_idx]

CSV 格式（UTF-8，可带 BOM）只导 variant，列名同上，params 写 JSON 字符串。

source_type 取 human / raw_ai_baseline / oneline_baseline / gold_bad，
其他任何值都当成候选 id（等价于 source_type=candidate, candidate_id=该值）。
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path

from .normalize import normalize

RESERVED = {"human", "raw_ai_baseline", "oneline_baseline", "gold_bad"}


class ImportErrorWB(ValueError):
    pass


def public_brief(brief: dict) -> dict:
    """去掉只有管理员能看的字段（原稿路径、授权说明等）。"""
    return {k: v for k, v in brief.items() if k not in ("source", "id", "notes_admin")}


def upsert_item(conn: sqlite3.Connection, brief: dict, is_example: bool = False) -> str:
    if "id" not in brief or brief.get("line") not in ("台词", "口播"):
        raise ImportErrorWB(f"brief 缺 id 或 line 不是 台词/口播：{brief.get('id')}")
    is_example = is_example or bool(brief.get("is_example"))
    conn.execute(
        "INSERT INTO item(id, line, brief_json, public_json, is_example) VALUES (?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET line=excluded.line, brief_json=excluded.brief_json, "
        "public_json=excluded.public_json, is_example=excluded.is_example",
        (brief["id"], brief["line"], json.dumps(brief, ensure_ascii=False),
         json.dumps(public_brief(brief), ensure_ascii=False), int(is_example)),
    )
    return brief["id"]


def _resolve_source(v: dict) -> tuple[str, str]:
    st = (v.get("source_type") or "").strip()
    cid = (v.get("candidate_id") or "").strip()
    if not st:
        raise ImportErrorWB("variant 缺 source_type")
    if st == "candidate":
        if not cid:
            raise ImportErrorWB("source_type=candidate 时必须给 candidate_id")
        return "candidate", cid
    if st in RESERVED:
        return st, st
    return "candidate", st


def add_variant(conn: sqlite3.Connection, v: dict, imported_from: str = "") -> int:
    item = conn.execute("SELECT line FROM item WHERE id=?", (v.get("item_id"),)).fetchone()
    if not item:
        raise ImportErrorWB(f"找不到 item：{v.get('item_id')}（先导入 brief）")
    text = v.get("text") or ""
    if not text.strip():
        raise ImportErrorWB(f"{v.get('item_id')} 有一条空文本")
    st, label = _resolve_source(v)
    params = v.get("params")
    if isinstance(params, (dict, list)):
        params = json.dumps(params, ensure_ascii=False)
    display = normalize(text, item["line"])
    cur = conn.execute(
        "INSERT INTO variant(item_id, raw_text, display_text, char_len) VALUES (?,?,?,?)",
        (v["item_id"], text, display, len(display.replace("\n", ""))),
    )
    vid = cur.lastrowid
    conn.execute(
        "INSERT INTO variant_source(variant_id, source_type, source_label, skill_git_hash, model, "
        "params_json, sample_idx, imported_from) VALUES (?,?,?,?,?,?,?,?)",
        (vid, st, label, v.get("skill_git_hash") or None, v.get("model") or None,
         params or None, int(v.get("sample_idx") or 0), imported_from),
    )
    return vid


def import_json(conn: sqlite3.Connection, data: dict | list, imported_from: str = "json") -> dict:
    if isinstance(data, list):
        data = {"variants": data}
    n_items = n_vars = 0
    with conn:
        for b in data.get("items", []):
            upsert_item(conn, b, is_example=bool(data.get("is_example")))
            n_items += 1
        for v in data.get("variants", []):
            add_variant(conn, v, imported_from)
            n_vars += 1
    return {"items": n_items, "variants": n_vars}


def import_csv_text(conn: sqlite3.Connection, text: str, imported_from: str = "csv") -> dict:
    text = text.lstrip("﻿")
    rows = list(csv.DictReader(io.StringIO(text)))
    n = 0
    with conn:
        for r in rows:
            add_variant(conn, {k.strip(): (val or "") for k, val in r.items() if k}, imported_from)
            n += 1
    return {"items": 0, "variants": n}


def import_path(conn: sqlite3.Connection, path: str | Path) -> dict:
    p = Path(path)
    content = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() == ".csv":
        return import_csv_text(conn, content, imported_from=p.name)
    return import_json(conn, json.loads(content), imported_from=p.name)
