"""随机化：每位评审、每道题独立随机左右，位置记录可复原，种子可复现。"""
import math

from workbench import batching, service
from workbench.db import connect
from workbench import importer
from conftest import SEED


def test_positions_recorded_consistently(conn, rater):
    batching.generate_batch(conn, rater["id"], "台词", n_pairwise=24, n_single=4, seed=11)
    for t in conn.execute("SELECT * FROM task WHERE kind='pairwise_pref'"):
        lo, hi = sorted((t["left_variant_id"], t["right_variant_id"]))
        assert (t["left_variant_id"] == hi) == bool(t["swapped"])


def test_left_right_is_balanced(conn):
    for k in range(20):
        r = service.create_rater(conn, f"评审{k}")
        for line in ("台词", "口播"):
            batching.generate_batch(conn, r["id"], line, n_pairwise=20, n_single=0, seed=1000 + 7 * k + (line == "台词"))
    swaps = [t["swapped"] for t in conn.execute(
        "SELECT swapped FROM task WHERE kind='pairwise_pref' AND control_type IS NULL")]
    n, k = len(swaps), sum(swaps)
    assert n >= 600
    # 4 个标准差以内
    assert abs(k - n / 2) < 4 * math.sqrt(n) / 2, (k, n)


def test_positions_independent_across_raters(conn):
    """不同评审拿到同一对稿件时，左右不是同一个模式。"""
    r1, r2 = service.create_rater(conn, "甲"), service.create_rater(conn, "乙")
    batching.generate_batch(conn, r1["id"], "台词", n_pairwise=30, n_single=0, seed=1)
    batching.generate_batch(conn, r2["id"], "台词", n_pairwise=30, n_single=0, seed=2)
    def layout(rid):
        return {frozenset((t["left_variant_id"], t["right_variant_id"])): t["left_variant_id"]
                for t in conn.execute("SELECT * FROM task WHERE rater_id=? AND kind='pairwise_pref' "
                                      "AND control_type IS NULL", (rid,))}
    a, b = layout(r1["id"]), layout(r2["id"])
    common = set(a) & set(b)
    assert len(common) >= 10
    same = sum(a[p] == b[p] for p in common)
    assert 0 < same < len(common)


def test_order_is_shuffled_and_seed_reproducible(tmp_path):
    def build(path, seed):
        c = connect(path)
        importer.import_path(c, SEED / "示例_briefs与稿件.json")
        importer.import_path(c, SEED / "示例_候选稿.csv")
        r = service.create_rater(c, "x")
        bid = batching.generate_batch(c, r["id"], "口播", n_pairwise=20, n_single=4, seed=seed)
        rows = [(t["kind"], t["left_variant_id"], t["right_variant_id"], t["control_type"])
                for t in c.execute("SELECT * FROM task WHERE batch_id=? ORDER BY display_order", (bid,))]
        assert c.execute("SELECT seed FROM batch WHERE id=?", (bid,)).fetchone()[0] == seed
        c.close()
        return rows
    a = build(tmp_path / "a.sqlite3", 42)
    b = build(tmp_path / "b.sqlite3", 42)
    c = build(tmp_path / "c.sqlite3", 43)
    assert a == b
    assert a != c
    kinds = [x[0] for x in a]
    assert kinds != sorted(kinds)  # 单篇题和两两题混排


def test_no_duplicate_pair_for_same_rater(conn, rater):
    batching.generate_batch(conn, rater["id"], "台词", n_pairwise=15, n_single=0, seed=1)
    batching.generate_batch(conn, rater["id"], "台词", n_pairwise=15, n_single=0, seed=2)
    pairs = [frozenset((t["left_variant_id"], t["right_variant_id"])) for t in conn.execute(
        "SELECT * FROM task WHERE rater_id=? AND kind='pairwise_pref' AND control_type IS NULL", (rater["id"],))]
    assert len(pairs) == len(set(pairs))


def test_length_filter_skips_mismatched_pairs(conn, rater):
    bid = batching.generate_batch(conn, rater["id"], "台词", n_pairwise=60, n_single=0, seed=1, max_len_ratio=1.2)
    for t in conn.execute("SELECT va.char_len a, vb.char_len b FROM task t JOIN variant va ON va.id=t.left_variant_id "
                          "JOIN variant vb ON vb.id=t.right_variant_id WHERE t.batch_id=? AND t.control_type IS NULL", (bid,)):
        assert max(t["a"], t["b"]) / min(t["a"], t["b"]) <= 1.2
