"""去盲：评审接口拿不到任何来源信息。"""
import json

from workbench import batching
from conftest import call


def _secrets(conn):
    """所有不该出现在评审接口里的字符串。"""
    out = set()
    for r in conn.execute("SELECT * FROM variant_source"):
        out.add(r["source_label"])
        out.add(r["source_type"])
        for k in ("skill_git_hash", "model", "params_json", "imported_from"):
            if r[k]:
                out.add(r[k])
    for r in conn.execute("SELECT id, brief_json FROM item"):
        out.add(r["id"])
        b = json.loads(r["brief_json"])
        out.update(v for v in b.get("source", {}).values() if isinstance(v, str))
    out.update({"control_type", "human_anchor", "ai_honeypot", "is_gold", "gold_expected", "swapped",
                "is_repeat_of", "variant_id", "left_variant_id", "source_label", "source_type"})
    return {s for s in out if s and len(s) >= 3}


def test_rater_api_never_leaks_source(conn, rater, app):
    for line in ("台词", "口播"):
        batching.generate_batch(conn, rater["id"], line, n_pairwise=20, n_single=4, seed=3)
    secrets_ = _secrets(conn)
    st, q = call(app, "GET", "/api/rater/queue", code=rater["code"])
    assert st == 200
    payloads = [json.dumps(q, ensure_ascii=False)]
    tasks = [t for b in q["batches"] for t in b["tasks"]]
    assert len(tasks) > 40
    for t in tasks:
        st, body = call(app, "GET", f"/api/rater/task/{t['id']}", code=rater["code"])
        assert st == 200
        assert set(body) == {"id", "kind", "line", "is_example", "context", "prompts", "texts", "judgment"}
        assert [x["side"] for x in body["texts"]] in (["A"], ["A", "B"])
        payloads.append(json.dumps(body, ensure_ascii=False))
    blob = "\n".join(payloads)
    leaked = sorted(s for s in secrets_ if s in blob)
    assert leaked == [], f"评审接口泄露了：{leaked}"


def test_public_ids_are_opaque(conn, rater):
    batching.generate_batch(conn, rater["id"], "台词", n_pairwise=10, n_single=2, seed=1)
    rows = conn.execute("SELECT id, public_id FROM task ORDER BY id").fetchall()
    ids = [r["public_id"] for r in rows]
    assert len(set(ids)) == len(ids)
    assert all(len(p) >= 12 for p in ids)
    # 不透明 id 和数据库自增 id、展示顺序都没有可见关系
    assert ids != sorted(ids)
    assert not any(p.removeprefix("t_").isdigit() for p in ids)


def test_rater_cannot_see_other_raters_tasks(conn, app):
    from workbench import service
    r1, r2 = service.create_rater(conn, "甲"), service.create_rater(conn, "乙")
    batching.generate_batch(conn, r1["id"], "口播", n_pairwise=8, n_single=2, seed=1)
    pid = conn.execute("SELECT public_id FROM task WHERE rater_id=? LIMIT 1", (r1["id"],)).fetchone()[0]
    assert call(app, "GET", f"/api/rater/task/{pid}", code=r2["code"])[0] == 404
    st, _ = call(app, "POST", f"/api/rater/task/{pid}/judgment", code=r2["code"],
                 body={"ai_conf_a": 3, "ai_conf_b": 3, "preference": "A", "duration_ms": 30000})
    assert st == 404
    assert call(app, "GET", "/api/rater/queue", code="wrong")[0] == 401


def test_admin_api_needs_token(app, rater):
    assert call(app, "GET", "/api/admin/overview")[0] == 403
    assert call(app, "GET", "/api/admin/overview", code=rater["code"])[0] == 403
    assert call(app, "GET", "/api/admin/export/csv", admin="nope")[0] == 403
    assert call(app, "GET", "/api/admin/overview", admin="admintok")[0] == 200


def test_display_text_is_normalized_not_raw(conn):
    raw = conn.execute(
        "SELECT v.raw_text, v.display_text FROM variant v JOIN variant_source s ON s.variant_id=v.id "
        "WHERE s.source_type='raw_ai_baseline' AND v.item_id='dlg-demo-01'").fetchone()
    assert "**" in raw["raw_text"]
    assert "**" not in raw["display_text"] and "#" not in raw["display_text"]


def test_public_brief_strips_admin_fields(conn):
    for r in conn.execute("SELECT public_json FROM item"):
        pub = json.loads(r["public_json"])
        assert "source" not in pub and "id" not in pub
