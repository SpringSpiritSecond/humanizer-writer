"""生成评审批次：选题、随机左右、混入对照题、打乱顺序。全部在服务端完成。

对照题四类（每批占 10–15%）：
- human_anchor：真人原稿单篇判别题（“像不像 AI”的人类锚点）
- ai_honeypot：AI 原稿（raw_ai_baseline）单篇判别题
- repeat：本批某道两两题左右调换后再出一遍，测自洽
- gold：真人原稿 vs 明显改坏的版本，有标准答案，测注意力
"""
from __future__ import annotations

import json
import random
import secrets
import sqlite3
from collections import Counter
from itertools import combinations

CONTROL_MIN, CONTROL_MAX, CONTROL_TARGET = 0.10, 0.15, 0.125
CONTROL_TYPES = ("human_anchor", "ai_honeypot", "repeat", "gold")
MIN_REPEAT_GAP = 5


class BatchError(ValueError):
    pass


def control_count(n_main: int, target: float = CONTROL_TARGET) -> int:
    """在 [10%, 15%] 里找最接近 target 的对照题数量（占全批的比例）。"""
    if not CONTROL_MIN <= target <= CONTROL_MAX:
        raise BatchError(f"对照题比例 {target} 不在 10%–15% 之间")
    best = None
    for k in range(1, n_main + 1):
        r = k / (n_main + k)
        if CONTROL_MIN - 1e-9 <= r <= CONTROL_MAX + 1e-9:
            if best is None or abs(r - target) < abs(best / (n_main + best) - target):
                best = k
    if best is None:
        raise BatchError(f"正式题只有 {n_main} 道，凑不出 10–15% 的对照题；每批至少 6 道正式题")
    return best


def _feasible(n_main, target):
    try:
        control_count(n_main, target)
        return True
    except BatchError:
        return False


def _variants(conn, line, labels=None):
    rows = conn.execute(
        "SELECT v.id, v.item_id, v.char_len, s.source_type, s.source_label FROM variant v "
        "JOIN variant_source s ON s.variant_id = v.id JOIN item i ON i.id = v.item_id "
        "WHERE i.line = ? ORDER BY v.id", (line,)).fetchall()
    out = [dict(r) for r in rows]
    if labels:
        out = [r for r in out if r["source_label"] in labels or r["source_type"] == "gold_bad"]
    return out


def _len_ok(a, b, max_ratio):
    lo, hi = sorted((a["char_len"], b["char_len"]))
    return lo > 0 and hi / lo <= max_ratio


def degrade(text: str) -> str:
    """生成一个明显改坏的金标题版本：截掉后半、重复一句、塞进套话。"""
    lines = [l for l in text.split("\n") if l.strip()]
    keep = lines[: max(1, (len(lines) + 1) // 2)]
    filler = ["总而言之，这件事情非常重要，我们一定要高度重视。",
              "综上所述，我们要不断努力，积极进取，共同创造更加美好的明天。",
              "总而言之，这件事情非常重要，我们一定要高度重视。"]
    return "\n".join(keep + [keep[0]] + filler)


def _gold_bad_for(conn, item_id, human_vid):
    row = conn.execute(
        "SELECT v.id FROM variant v JOIN variant_source s ON s.variant_id=v.id "
        "WHERE v.item_id=? AND s.source_type='gold_bad' ORDER BY v.id LIMIT 1", (item_id,)).fetchone()
    if row:
        return row["id"]
    text = conn.execute("SELECT display_text FROM variant WHERE id=?", (human_vid,)).fetchone()[0]
    bad = degrade(text)
    cur = conn.execute("INSERT INTO variant(item_id, raw_text, display_text, char_len) VALUES (?,?,?,?)",
                       (item_id, bad, bad, len(bad.replace("\n", ""))))
    conn.execute("INSERT INTO variant_source(variant_id, source_type, source_label, imported_from) "
                 "VALUES (?, 'gold_bad', 'gold_bad', 'auto_gold')", (cur.lastrowid,))
    return cur.lastrowid


def generate_batch(conn: sqlite3.Connection, rater_id: int, line: str, n_pairwise: int = 24,
                   n_single: int = 4, sources: list[str] | None = None,
                   control_ratio: float = CONTROL_TARGET, seed: int | None = None,
                   max_len_ratio: float = 1.5) -> int:
    if not conn.execute("SELECT 1 FROM rater WHERE id=?", (rater_id,)).fetchone():
        raise BatchError(f"没有这个评审：{rater_id}")
    seed = seed if seed is not None else secrets.randbits(31)
    rng = random.Random(seed)
    allv = _variants(conn, line)
    pool = [v for v in _variants(conn, line, sources) if v["source_type"] != "gold_bad"]
    if not pool:
        raise BatchError(f"{line} 线没有可用的稿件")

    # 已有分配，用来均衡覆盖、避免同一评审重复看同一对
    seen_pairs_rater, pair_count, single_seen_rater, single_count = set(), Counter(), set(), Counter()
    for t in conn.execute("SELECT rater_id, kind, left_variant_id l, right_variant_id r FROM task "
                          "WHERE control_type IS NULL OR control_type NOT IN ('repeat','gold')"):
        if t["kind"] == "pairwise_pref":
            key = frozenset((t["l"], t["r"]))
            pair_count[key] += 1
            if t["rater_id"] == rater_id:
                seen_pairs_rater.add(key)
        else:
            single_count[t["l"]] += 1
            if t["rater_id"] == rater_id:
                single_seen_rater.add(t["l"])

    by_item: dict[str, list] = {}
    for v in pool:
        by_item.setdefault(v["item_id"], []).append(v)
    cands, skipped_len = [], 0
    for item_id, vs in by_item.items():
        for a, b in combinations(vs, 2):
            if a["source_label"] == b["source_label"] or frozenset((a["id"], b["id"])) in seen_pairs_rater:
                continue
            if not _len_ok(a, b, max_len_ratio):
                skipped_len += 1        # 长度差太多本身就会泄露来源，不配对，但记下来
                continue
            cands.append((a, b))
    paired_labels = {v["source_label"] for c in cands for v in c}
    unpaired = sorted({v["source_label"] for v in pool} - paired_labels)
    rng.shuffle(cands)

    main: list[dict] = []
    src_pair_used, item_used = Counter(), Counter()
    for _ in range(min(n_pairwise, len(cands))):
        def cost(c):
            a, b = c
            return (pair_count[frozenset((a["id"], b["id"]))],
                    src_pair_used[frozenset((a["source_label"], b["source_label"]))],
                    item_used[a["item_id"]])
        best = min(cands, key=cost)
        cands.remove(best)
        a, b = best
        src_pair_used[frozenset((a["source_label"], b["source_label"]))] += 1
        item_used[a["item_id"]] += 1
        main.append({"kind": "pairwise_pref", "item_id": a["item_id"], "pair": (a["id"], b["id"])})

    singles = [v for v in pool if v["id"] not in single_seen_rater]
    rng.shuffle(singles)
    singles.sort(key=lambda v: single_count[v["id"]])
    for v in singles[:n_single]:
        main.append({"kind": "single_turing", "item_id": v["item_id"], "variant": v["id"]})
    if not main:
        raise BatchError("没有还没分配给这位评审的题了")

    # 对照题。有些正式题数（如 10、11）凑不出 10–15%，就去掉末尾几道正式题
    while len(main) > 6 and not _feasible(len(main), control_ratio):
        main.pop()
    n_ctrl = control_count(len(main), control_ratio)
    humans = [v for v in allv if v["source_type"] == "human"]
    honeypots = [v for v in allv if v["source_type"] == "raw_ai_baseline"]
    pairwise_main = [m for m in main if m["kind"] == "pairwise_pref"]
    available = [c for c in CONTROL_TYPES if
                 (c == "human_anchor" and humans) or (c == "ai_honeypot" and honeypots) or
                 (c == "repeat" and pairwise_main) or (c == "gold" and humans)]
    if not available:
        raise BatchError("没有真人原稿或 AI 原稿，无法生成对照题")
    # 对照题不足 4 道时哪几类先出是随机的，多批下来四类都能覆盖
    rng.shuffle(available)
    controls = []
    for i in range(n_ctrl):
        ctype = available[i % len(available)]
        if ctype == "human_anchor":
            v = rng.choice(humans)
            controls.append({"kind": "single_turing", "item_id": v["item_id"], "variant": v["id"], "control": ctype})
        elif ctype == "ai_honeypot":
            v = rng.choice(honeypots)
            controls.append({"kind": "single_turing", "item_id": v["item_id"], "variant": v["id"], "control": ctype})
        elif ctype == "repeat":
            orig = rng.choice(pairwise_main)
            controls.append({"kind": "pairwise_pref", "item_id": orig["item_id"], "repeat_of": orig, "control": ctype})
        else:
            h = rng.choice(humans)
            controls.append({"kind": "pairwise_pref", "item_id": h["item_id"], "gold_human": h["id"], "control": ctype})

    tasks = main + controls
    rng.shuffle(tasks)
    # 重复题必须排在原题之后，至少隔 MIN_REPEAT_GAP 道（批次够长时）
    for t in [t for t in tasks if t.get("control") == "repeat"]:
        tasks.remove(t)
        oi = tasks.index(t["repeat_of"])
        lo = min(oi + 1 + MIN_REPEAT_GAP, len(tasks))
        tasks.insert(rng.randint(lo, len(tasks)), t)

    params = {"n_pairwise": n_pairwise, "n_single": n_single, "sources": sources,
              "max_len_ratio": max_len_ratio, "skipped_len_pairs": skipped_len,
              "unpaired_sources": unpaired, "n_main": len(main), "n_control": len(controls)}
    with conn:
        bid = conn.execute("INSERT INTO batch(rater_id, line, seed, control_ratio, params_json) VALUES (?,?,?,?,?)",
                           (rater_id, line, seed, control_ratio, json.dumps(params, ensure_ascii=False))).lastrowid
        for order, t in enumerate(tasks):
            kw = dict(control_type=t.get("control"), is_gold=0, gold_expected=None, is_repeat_of=None)
            if t["kind"] == "single_turing":
                left, right, swapped = t["variant"], None, 0
            elif t.get("control") == "repeat":
                o = t["repeat_of"]
                left, right, swapped = o["right"], o["left"], 1 - o["swapped"]
                kw["is_repeat_of"] = o["task_id"]
            else:
                if t.get("control") == "gold":
                    bad = _gold_bad_for(conn, t["item_id"], t["gold_human"])
                    pair = (t["gold_human"], bad)
                    kw["is_gold"] = 1
                else:
                    pair = t["pair"]
                lo_id, hi_id = sorted(pair)
                swapped = int(rng.random() < 0.5)       # 每个评审、每道题独立随机
                left, right = (hi_id, lo_id) if swapped else (lo_id, hi_id)
                if kw["is_gold"]:
                    kw["gold_expected"] = "A" if left == t["gold_human"] else "B"
            tid = conn.execute(
                "INSERT INTO task(public_id, batch_id, rater_id, kind, item_id, left_variant_id, right_variant_id, "
                "swapped, display_order, control_type, is_gold, gold_expected, is_repeat_of) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("t_" + secrets.token_urlsafe(9), bid, rater_id, t["kind"], t["item_id"], left, right, swapped,
                 order, kw["control_type"], kw["is_gold"], kw["gold_expected"], kw["is_repeat_of"])).lastrowid
            t.update(task_id=tid, left=left, right=right, swapped=swapped)
    return bid
