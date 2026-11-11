"""对照题：比例 10–15%，四类都有，各自的构造正确。"""
import pytest

from workbench import batching, service


@pytest.mark.parametrize("n_main", [n for n in range(6, 81) if n not in (10, 11)])
def test_control_count_in_range(n_main):
    k = batching.control_count(n_main)
    assert 0.10 <= k / (n_main + k) <= 0.15


@pytest.mark.parametrize("n_main", [10, 11])
def test_infeasible_sizes_are_trimmed(conn, rater, n_main):
    """10、11 道正式题凑不出 10–15%，生成批次时会少出一两道正式题。"""
    with pytest.raises(batching.BatchError):
        batching.control_count(n_main)
    bid = batching.generate_batch(conn, rater["id"], "台词", n_pairwise=n_main, n_single=0, seed=1)
    rows = conn.execute("SELECT control_type FROM task WHERE batch_id=?", (bid,)).fetchall()
    ctrl = sum(r[0] is not None for r in rows)
    assert 0.10 <= ctrl / len(rows) <= 0.15


def test_control_count_rejects_tiny_batches():
    with pytest.raises(batching.BatchError):
        batching.control_count(5)
    with pytest.raises(batching.BatchError):
        batching.control_count(30, target=0.2)


@pytest.mark.parametrize("line,pairs,singles", [("台词", 24, 4), ("口播", 20, 6), ("台词", 30, 0), ("口播", 8, 2)])
def test_batch_ratio_and_types(conn, rater, line, pairs, singles):
    bid = batching.generate_batch(conn, rater["id"], line, n_pairwise=pairs, n_single=singles, seed=5)
    rows = conn.execute("SELECT * FROM task WHERE batch_id=?", (bid,)).fetchall()
    ctrl = [r for r in rows if r["control_type"]]
    assert 0.10 <= len(ctrl) / len(rows) <= 0.15
    if len(ctrl) >= 4:
        assert {r["control_type"] for r in ctrl} == set(batching.CONTROL_TYPES)
    orders = sorted(r["display_order"] for r in rows)
    assert orders == list(range(len(rows)))


def test_each_control_is_built_correctly(conn, rater):
    bid = batching.generate_batch(conn, rater["id"], "台词", n_pairwise=30, n_single=4, seed=9)
    src = {r["variant_id"]: r["source_type"] for r in conn.execute("SELECT * FROM variant_source")}
    tasks = {r["id"]: r for r in conn.execute("SELECT * FROM task WHERE batch_id=?", (bid,))}
    seen = set()
    for t in tasks.values():
        ct = t["control_type"]
        if ct == "human_anchor":
            assert t["kind"] == "single_turing" and src[t["left_variant_id"]] == "human"
        elif ct == "ai_honeypot":
            assert t["kind"] == "single_turing" and src[t["left_variant_id"]] == "raw_ai_baseline"
        elif ct == "repeat":
            o = tasks[t["is_repeat_of"]]
            assert o["control_type"] is None and o["kind"] == "pairwise_pref"
            assert (t["left_variant_id"], t["right_variant_id"]) == (o["right_variant_id"], o["left_variant_id"])
            assert t["swapped"] == 1 - o["swapped"]
            assert t["display_order"] > o["display_order"]
            assert t["display_order"] - o["display_order"] >= min(batching.MIN_REPEAT_GAP, len(tasks) - 1 - o["display_order"])
        elif ct == "gold":
            assert t["is_gold"] == 1
            sides = {"A": t["left_variant_id"], "B": t["right_variant_id"]}
            assert src[sides[t["gold_expected"]]] == "human"
            other = sides["B" if t["gold_expected"] == "A" else "A"]
            assert src[other] == "gold_bad"
        else:
            assert t["is_gold"] == 0 and t["is_repeat_of"] is None
        seen.add(ct)
    assert {"human_anchor", "ai_honeypot", "repeat", "gold"} <= seen


def test_gold_bad_variants_never_enter_main_tasks(conn):
    for k in range(6):
        r = service.create_rater(conn, f"评审{k}")
        batching.generate_batch(conn, r["id"], "口播", n_pairwise=24, n_single=4, seed=k)
    bad = {r[0] for r in conn.execute("SELECT variant_id FROM variant_source WHERE source_type='gold_bad'")}
    assert bad
    for t in conn.execute("SELECT * FROM task WHERE control_type IS NULL OR control_type != 'gold'"):
        assert t["left_variant_id"] not in bad and t["right_variant_id"] not in bad


def test_source_filter(conn, rater):
    bid = batching.generate_batch(conn, rater["id"], "台词", n_pairwise=10, n_single=4, seed=1,
                                  sources=["oneline_baseline", "示例候选-甲"])
    labels = {r[0] for r in conn.execute(
        "SELECT s.source_label FROM task t JOIN variant_source s ON s.variant_id IN (t.left_variant_id, t.right_variant_id) "
        "WHERE t.batch_id=? AND t.control_type IS NULL", (bid,))}
    assert labels == {"oneline_baseline", "示例候选-甲"}
