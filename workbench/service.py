"""评审端和管理端的业务逻辑。

评审端函数只读 item.public_json、variant.display_text 和 task 的展示字段，
从不读 variant_source，也不返回 variant id、item id、对照题类型。
"""
from __future__ import annotations

import json
import secrets
import sqlite3

TAGS = [
    {"key": "q", "id": "套话", "hint": "空话、模板句、总结拔高"},
    {"key": "w", "id": "节奏单一", "hint": "句子长短、段落结构太齐整"},
    {"key": "e", "id": "不像人说话", "hint": "书面腔，没人这么开口"},
    {"key": "r", "id": "电报体", "hint": "关联词删光，读着断断续续"},
    {"key": "t", "id": "编出来的细节", "hint": "brief 里没有的经历、案例、数字"},
    {"key": "y", "id": "事实改错", "hint": "数字、专名、beat、锁定台词被改了"},
    {"key": "u", "id": "改过头", "hint": "为去味而去味，反而别扭"},
]
TAG_IDS = {t["id"] for t in TAGS}

# 答得过快：低于 MIN_MS，或者折合阅读速度超过 MAX_CHARS_PER_MIN（中文默读一般 300–600 字/分）
MIN_MS = 4000
MAX_CHARS_PER_MIN = 1500

PROMPTS = {
    "台词": {
        "turing": "这段台词像不像 AI 写的？",
        "pref": "哪段演员更好演、更像人说话？",
        "note": "所有版本用的是同一张场景卡，只有对白不同。",
    },
    "口播": {
        "turing": "这段口播像不像 AI 写的？",
        "pref": "哪段你更愿意听完？",
        "note": "请把每段小声读出来再判断。",
    },
}
CONF_LABELS = ["1 肯定是人写的", "2 可能是人写的", "3 说不准", "4 可能是 AI 写的", "5 肯定是 AI 写的"]


class ApiError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status, self.msg = status, msg


# ---------- 评审端 ----------

def rater_by_code(conn, code: str):
    if not code:
        raise ApiError(401, "需要评审码")
    r = conn.execute("SELECT id, name FROM rater WHERE code=?", (code,)).fetchone()
    if not r:
        raise ApiError(401, "评审码不对")
    return r


def rater_queue(conn, rater_id: int) -> dict:
    rows = conn.execute(
        "SELECT t.public_id, t.batch_id, t.display_order, t.kind, j.id IS NOT NULL AS done "
        "FROM task t LEFT JOIN judgment j ON j.task_id=t.id WHERE t.rater_id=? "
        "ORDER BY t.batch_id, t.display_order", (rater_id,)).fetchall()
    batches: dict[int, list] = {}
    for r in rows:
        batches.setdefault(r["batch_id"], []).append({"id": r["public_id"], "kind": r["kind"], "done": bool(r["done"])})
    # 批次也用序号而不是数据库 id
    return {"batches": [{"no": i + 1, "tasks": ts} for i, (_, ts) in enumerate(sorted(batches.items()))]}


def _public_context(line: str, public: dict) -> dict:
    if line == "台词":
        return {"scene_card": public.get("scene_card", {}), "locked": public.get("locked", {}),
                "target": public.get("target", {})}
    return {"facts": public.get("facts", []), "must_include": public.get("must_include", {}),
            "must_not": public.get("must_not", []), "audience": public.get("audience"),
            "speaker": public.get("speaker"), "target": public.get("target", {})}


def rater_task(conn, rater_id: int, public_id: str) -> dict:
    t = conn.execute(
        "SELECT t.id, t.public_id, t.kind, i.line, i.public_json, i.is_example, "
        "va.display_text AS text_a, vb.display_text AS text_b "
        "FROM task t JOIN item i ON i.id=t.item_id JOIN variant va ON va.id=t.left_variant_id "
        "LEFT JOIN variant vb ON vb.id=t.right_variant_id WHERE t.public_id=? AND t.rater_id=?",
        (public_id, rater_id)).fetchone()
    if not t:
        raise ApiError(404, "没有这道题")
    texts = [{"side": "A", "text": t["text_a"]}]
    if t["kind"] == "pairwise_pref":
        texts.append({"side": "B", "text": t["text_b"]})
    j = conn.execute("SELECT ai_conf_a, ai_conf_b, preference, tags_json, spans_json, reason "
                     "FROM judgment WHERE task_id=?", (t["id"],)).fetchone()
    prev = None
    if j:
        prev = {"ai_conf_a": j["ai_conf_a"], "ai_conf_b": j["ai_conf_b"], "preference": j["preference"],
                "tags": json.loads(j["tags_json"]), "spans": json.loads(j["spans_json"]), "reason": j["reason"]}
    return {
        "id": t["public_id"], "kind": t["kind"], "line": t["line"], "is_example": bool(t["is_example"]),
        "context": _public_context(t["line"], json.loads(t["public_json"])),
        "prompts": PROMPTS[t["line"]], "texts": texts, "judgment": prev,
    }


def too_fast(duration_ms: int, chars: int) -> bool:
    if duration_ms < MIN_MS:
        return True
    return chars / (duration_ms / 60000) > MAX_CHARS_PER_MIN


def submit_judgment(conn, rater_id: int, public_id: str, body: dict) -> dict:
    t = conn.execute(
        "SELECT t.id, t.kind, va.char_len AS la, vb.char_len AS lb FROM task t "
        "JOIN variant va ON va.id=t.left_variant_id LEFT JOIN variant vb ON vb.id=t.right_variant_id "
        "WHERE t.public_id=? AND t.rater_id=?", (public_id, rater_id)).fetchone()
    if not t:
        raise ApiError(404, "没有这道题")

    def conf(k):
        v = body.get(k)
        if v is None:
            return None
        if not isinstance(v, int) or not 1 <= v <= 5:
            raise ApiError(400, f"{k} 要在 1–5 之间")
        return v

    a, b, pref = conf("ai_conf_a"), conf("ai_conf_b"), body.get("preference")
    if a is None:
        raise ApiError(400, "先回答判别题（A 像不像 AI）")
    if t["kind"] == "pairwise_pref":
        if b is None:
            raise ApiError(400, "先回答判别题（B 像不像 AI）")
        if pref not in ("A", "B", "tie", "both_bad"):
            raise ApiError(400, "偏好要选 A / B / 一样好 / 都不行")
    else:
        b, pref = None, None
    sides = ("A", "B") if t["kind"] == "pairwise_pref" else ("A",)
    tags = body.get("tags") or {}
    tags = {s: sorted({x for x in tags.get(s, []) if x in TAG_IDS}) for s in sides}
    spans = []
    for s in body.get("spans") or []:
        if s.get("side") in sides and isinstance(s.get("start"), int) and isinstance(s.get("end"), int) \
                and s["end"] > s["start"]:
            tag = s.get("tag") if s.get("tag") in TAG_IDS else None
            spans.append({"side": s["side"], "start": s["start"], "end": s["end"],
                          "text": str(s.get("text", ""))[:500], "tag": tag})
    dur = body.get("duration_ms")
    if not isinstance(dur, int) or dur < 0:
        raise ApiError(400, "缺少用时")
    chars = (t["la"] or 0) + (t["lb"] or 0)
    old = conn.execute("SELECT duration_ms FROM judgment WHERE task_id=?", (t["id"],)).fetchone()
    with conn:
        if old:
            total = old["duration_ms"] + dur
            conn.execute(
                "UPDATE judgment SET ai_conf_a=?, ai_conf_b=?, preference=?, tags_json=?, spans_json=?, reason=?, "
                "duration_ms=?, too_fast=?, revisions=revisions+1, updated_at=datetime('now') WHERE task_id=?",
                (a, b, pref, json.dumps(tags, ensure_ascii=False), json.dumps(spans, ensure_ascii=False),
                 str(body.get("reason", ""))[:2000], total, int(too_fast(total, chars)), t["id"]))
        else:
            total = dur
            conn.execute(
                "INSERT INTO judgment(task_id, rater_id, ai_conf_a, ai_conf_b, preference, tags_json, spans_json, "
                "reason, duration_ms, too_fast) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (t["id"], rater_id, a, b, pref, json.dumps(tags, ensure_ascii=False),
                 json.dumps(spans, ensure_ascii=False), str(body.get("reason", ""))[:2000], dur,
                 int(too_fast(dur, chars))))
    # 不回显 too_fast 之外的任何判定结果（金标题对错不告诉评审）
    return {"ok": True, "too_fast": too_fast(total, chars)}


# ---------- 管理端 ----------

def create_rater(conn, name: str, expertise: str = "", simulated: bool = False) -> dict:
    code = secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
    with conn:
        rid = conn.execute("INSERT INTO rater(name, code, expertise, is_simulated) VALUES (?,?,?,?)",
                           (name, code, expertise, int(simulated))).lastrowid
    return {"id": rid, "name": name, "code": code}


def overview(conn) -> dict:
    items = [dict(r) for r in conn.execute(
        "SELECT i.line, COUNT(DISTINCT i.id) items, COUNT(v.id) variants, MAX(i.is_example) has_examples "
        "FROM item i LEFT JOIN variant v ON v.item_id=i.id GROUP BY i.line")]
    sources = [dict(r) for r in conn.execute(
        "SELECT i.line, s.source_type, s.source_label, COUNT(*) n, "
        "GROUP_CONCAT(DISTINCT s.skill_git_hash) hashes, GROUP_CONCAT(DISTINCT s.model) models "
        "FROM variant_source s JOIN variant v ON v.id=s.variant_id JOIN item i ON i.id=v.item_id "
        "GROUP BY i.line, s.source_type, s.source_label ORDER BY i.line, s.source_type, s.source_label")]
    raters = [dict(r) for r in conn.execute(
        "SELECT r.id, r.name, r.code, r.expertise, r.is_simulated, r.calibration_score, r.position_bias, "
        "r.self_consistency, COUNT(t.id) tasks, COUNT(j.id) done, SUM(j.too_fast) too_fast, "
        "CAST(AVG(j.duration_ms) AS INTEGER) avg_ms "
        "FROM rater r LEFT JOIN task t ON t.rater_id=r.id LEFT JOIN judgment j ON j.task_id=t.id "
        "GROUP BY r.id ORDER BY r.id")]
    batches = [dict(r) for r in conn.execute(
        "SELECT b.id, b.line, r.name rater, b.seed, b.created_at, COUNT(t.id) tasks, COUNT(j.id) done, "
        "SUM(t.control_type IS NOT NULL) controls FROM batch b JOIN rater r ON r.id=b.rater_id "
        "LEFT JOIN task t ON t.batch_id=b.id LEFT JOIN judgment j ON j.task_id=t.id "
        "GROUP BY b.id ORDER BY b.id DESC")]
    return {"items": items, "sources": sources, "raters": raters, "batches": batches}
