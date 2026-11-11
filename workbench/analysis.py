"""分析：Bradley-Terry 分（按条目 cluster bootstrap 的置信区间）、检出率、Krippendorff α、评审质量。

只用标准库。每条线（台词 / 口播）分开算，系统 = variant_source.source_label。

口径：
- BT 只用正式两两题（不含金标题和重复题）；“一样好”记各半场胜，“都不行”不进 BT，单列比例。
- 检出率 = 判别分 ≥ 4（“可能/肯定是 AI 写的”）的比例。所有题里每一篇被打的判别分都算，
  金标题的改坏版本除外。“相对位置” = (检出率 − 真人锚点) / (AI 蜜罐 − 真人锚点)，
  0 表示和真人一样，1 表示和 AI 原稿一样。
- α：判别分（有序，单位 = 一篇稿件）、偏好（有序 前好/一样/后好，单位 = 同一条目的一对稿件）、
  每个标签（名义 0/1，单位 = 一篇稿件）。同一评审对同一单位只取第一次（重复题不计）。
- 默认剔除答得过快的作答，模拟评审照算但在报告里标出。
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict

from .exporter import records

AI_THRESHOLD = 4


# ---------- 基础统计 ----------

def binom_two_sided(k: int, n: int, p: float = 0.5) -> float:
    if n == 0:
        return 1.0
    pk = math.comb(n, k) * p ** k * (1 - p) ** (n - k)
    tot = sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(n + 1)
              if math.comb(n, i) * p ** i * (1 - p) ** (n - i) <= pk * (1 + 1e-9))
    return min(1.0, tot)


def percentile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return xs[f] if f == c else xs[f] + (xs[c] - xs[f]) * (k - f)


# ---------- Bradley-Terry ----------

def bt_fit(games, systems, prior=0.5, iters=1000, tol=1e-9):
    """games: [(i, j, score_i)]，score_i ∈ {1, 0.5, 0}。MM 算法（Hunter 2004）。

    prior：每对系统之间加 prior 场虚拟平局，避免全胜/全负时发散，也让没交过手的系统可比。
    返回 {system: Elo 式分数}，1000 = 几何平均水平，差 400 分 ≈ 10:1 胜算。
    """
    idx = {s: k for k, s in enumerate(systems)}
    n = len(systems)
    wins = [0.0] * n
    cnt = [[0.0] * n for _ in range(n)]
    for i, j, s in games:
        a, b = idx[i], idx[j]
        wins[a] += s
        wins[b] += 1 - s
        cnt[a][b] += 1
        cnt[b][a] += 1
    for a in range(n):
        for b in range(n):
            if a != b:
                cnt[a][b] += prior
        wins[a] += prior * (n - 1) / 2
    p = [1.0] * n
    for _ in range(iters):
        newp = []
        for a in range(n):
            den = sum(cnt[a][b] / (p[a] + p[b]) for b in range(n) if b != a)
            newp.append(wins[a] / den if den > 0 else p[a])
        g = math.exp(sum(math.log(x) for x in newp) / n)
        newp = [x / g for x in newp]
        if max(abs(x - y) for x, y in zip(newp, p)) < tol:
            p = newp
            break
        p = newp
    return {s: 1000 + 400 * math.log10(p[idx[s]]) for s in systems}


# ---------- Krippendorff α ----------

def krippendorff_alpha(units: dict, metric: str = "ordinal"):
    """units: {unit: [value, ...]}（每个评审一个值，缺失就不放）。metric: nominal / ordinal / interval。"""
    units = {u: vs for u, vs in units.items() if len(vs) >= 2}
    if not units:
        return None
    cats = sorted({v for vs in units.values() for v in vs})
    o = defaultdict(float)
    for vs in units.values():
        m = len(vs)
        for i, a in enumerate(vs):
            for j, b in enumerate(vs):
                if i != j:
                    o[(a, b)] += 1 / (m - 1)
    nc = {c: sum(o[(c, k)] for k in cats) for c in cats}
    n = sum(nc.values())
    if n <= 1:
        return None

    def d2(c, k):
        if c == k:
            return 0.0
        if metric == "nominal":
            return 1.0
        if metric == "interval":
            return float(c - k) ** 2
        lo, hi = sorted((cats.index(c), cats.index(k)))
        s = sum(nc[cats[g]] for g in range(lo, hi + 1)) - (nc[c] + nc[k]) / 2
        return s * s

    do = sum(o[(c, k)] * d2(c, k) for c in cats for k in cats) / n
    de = sum(nc[c] * nc[k] * d2(c, k) for c in cats for k in cats) / (n * (n - 1))
    if de == 0:
        return None
    return 1 - do / de


def alpha_verdict(a):
    if a is None:
        return "数据不够"
    if a >= 0.80:
        return "可依赖"
    if a >= 0.667:
        return "只能作暂定结论"
    return "要重写锚点或删掉"


# ---------- 主流程 ----------

def _ratings(recs):
    """每篇稿件被打的判别分：(item, variant_id, label, conf, rec)。"""
    for r in recs:
        for side in ("a", "b"):
            if r[f"ai_conf_{side}"] is None or r[f"{side}_source_type"] == "gold_bad":
                continue
            yield r["item_id"], r[f"{side}_variant_id"], r[f"{side}_source_label"], r[f"ai_conf_{side}"], r


def _games(recs):
    out = []
    for r in recs:
        if r["kind"] != "pairwise_pref" or r["control_type"] in ("gold", "repeat"):
            continue
        if r["preference"] not in ("A", "B", "tie"):
            continue
        s = {"A": 1.0, "B": 0.0, "tie": 0.5}[r["preference"]]
        out.append((r["item_id"], r["a_source_label"], r["b_source_label"], s))
    return out


def _detection(ratings_by_item, items):
    hit, tot = Counter(), Counter()
    for it in items:
        for label, conf in ratings_by_item.get(it, []):
            tot[label] += 1
            hit[label] += conf >= AI_THRESHOLD
    return {s: hit[s] / tot[s] for s in tot}


def analyze_line(recs, line, n_boot=1000, seed=0):
    recs = [r for r in recs if r["line"] == line]
    rng = random.Random(seed)
    games = _games(recs)
    ratings_by_item = defaultdict(list)
    for item, _vid, label, conf, _r in _ratings(recs):
        ratings_by_item[item].append((label, conf))
    systems = sorted({g[1] for g in games} | {g[2] for g in games} |
                     {lab for v in ratings_by_item.values() for lab, _ in v})
    out = {"line": line, "n_judgments": len(recs), "n_games": len(games), "systems": {}}
    if not systems:
        return out

    games_by_item = defaultdict(list)
    for it, a, b, s in games:
        games_by_item[it].append((a, b, s))
    items = sorted(set(games_by_item) | set(ratings_by_item))
    bt_systems = sorted({g[1] for g in games} | {g[2] for g in games})
    bt = bt_fit([(a, b, s) for _, a, b, s in games], bt_systems) if bt_systems else {}
    det = _detection(ratings_by_item, items)

    boot_bt, boot_det = defaultdict(list), defaultdict(list)
    for _ in range(n_boot if items else 0):
        sample = [rng.choice(items) for _ in items]
        g = [x for it in sample for x in games_by_item.get(it, [])]
        if g and bt_systems:
            for s, v in bt_fit(g, bt_systems).items():
                boot_bt[s].append(v)
        for s, v in _detection(ratings_by_item, sample).items():
            boot_det[s].append(v)

    # 胜率、都不行比例、对真人胜率
    wins, n_games, both_bad, n_pairs, vs_human = Counter(), Counter(), Counter(), Counter(), defaultdict(lambda: [0.0, 0])
    for r in recs:
        if r["kind"] != "pairwise_pref" or r["control_type"] in ("gold", "repeat"):
            continue
        a, b = r["a_source_label"], r["b_source_label"]
        n_pairs[a] += 1
        n_pairs[b] += 1
        if r["preference"] == "both_bad":
            both_bad[a] += 1
            both_bad[b] += 1
            continue
        s = {"A": 1.0, "B": 0.0, "tie": 0.5}.get(r["preference"])
        if s is None:
            continue
        wins[a] += s
        wins[b] += 1 - s
        n_games[a] += 1
        n_games[b] += 1
        if b == "human":
            vs_human[a][0] += s
            vs_human[a][1] += 1
        if a == "human":
            vs_human[b][0] += 1 - s
            vs_human[b][1] += 1

    h, hp = det.get("human"), det.get("raw_ai_baseline")
    tag_count, rating_count = defaultdict(Counter), Counter()
    for r in recs:
        for side in ("a", "b"):
            lab = r[f"{side}_source_label"]
            if lab is None or r[f"ai_conf_{side}"] is None:
                continue
            rating_count[lab] += 1
            for t in r[f"tags_{side}"]:
                tag_count[lab][t] += 1
    for s in systems:
        d = det.get(s)
        out["systems"][s] = {
            "bt": bt.get(s), "bt_ci": [percentile(boot_bt[s], .025), percentile(boot_bt[s], .975)] if boot_bt[s] else None,
            "games": n_games[s], "win_rate": wins[s] / n_games[s] if n_games[s] else None,
            "both_bad_rate": both_bad[s] / n_pairs[s] if n_pairs[s] else None,
            "win_rate_vs_human": vs_human[s][0] / vs_human[s][1] if vs_human[s][1] else None,
            "n_ratings": sum(1 for v in ratings_by_item.values() for lab, _ in v if lab == s),
            "detection_rate": d,
            "detection_ci": [percentile(boot_det[s], .025), percentile(boot_det[s], .975)] if boot_det[s] else None,
            "relative_to_anchors": (d - h) / (hp - h) if None not in (d, h, hp) and hp != h else None,
            "tags_per_rating": {t: c / rating_count[s] for t, c in tag_count[s].most_common()} if rating_count[s] else {},
        }

    # Krippendorff α
    seen = set()
    conf_units, pref_units, tag_units = defaultdict(list), defaultdict(list), defaultdict(lambda: defaultdict(list))
    all_tags = sorted({t for r in recs for side in ("a", "b") for t in r[f"tags_{side}"]})
    for r in recs:
        if r["control_type"] == "repeat":
            continue
        for side in ("a", "b"):
            vid = r[f"{side}_variant_id"]
            if vid is None or r[f"ai_conf_{side}"] is None or r[f"{side}_source_type"] == "gold_bad":
                continue
            if (r["rater_id"], "v", vid) in seen:
                continue
            seen.add((r["rater_id"], "v", vid))
            conf_units[vid].append(r[f"ai_conf_{side}"])
            for t in all_tags:
                tag_units[t][vid].append(int(t in r[f"tags_{side}"]))
        if r["kind"] == "pairwise_pref" and r["preference"] in ("A", "B", "tie") and not r["is_gold"]:
            va, vb = r["a_variant_id"], r["b_variant_id"]
            key = (min(va, vb), max(va, vb))
            if (r["rater_id"], "p", key) in seen:
                continue
            seen.add((r["rater_id"], "p", key))
            first_wins = (r["preference"] == "A") == (va == key[0])
            pref_units[key].append(2 if r["preference"] == "tie" else (1 if first_wins else 3))
    alphas = {"判别分（有序）": krippendorff_alpha(conf_units, "ordinal"),
              "偏好（有序）": krippendorff_alpha(pref_units, "ordinal")}
    for t in all_tags:
        alphas[f"标签·{t}（名义）"] = krippendorff_alpha(tag_units[t], "nominal")
    out["alpha"] = {k: {"alpha": v, "verdict": alpha_verdict(v),
                        "units": len([1 for vs in (conf_units if '判别' in k else pref_units if '偏好' in k
                                                   else tag_units[k[3:-4]]).values() if len(vs) >= 2])}
                    for k, v in alphas.items()}
    # 残留 AI 腔：划选片段
    spans = Counter()
    for r in recs:
        for sp in r["spans"]:
            lab = r[f"{sp['side'].lower()}_source_label"]
            spans[(lab, sp.get("tag") or "", sp["text"])] += 1
    out["top_spans"] = [{"source": k[0], "tag": k[1], "text": k[2], "count": c} for k, c in spans.most_common(30)]
    return out


def rater_quality(all_recs):
    by_rater = defaultdict(list)
    for r in all_recs:
        by_rater[r["rater_id"]].append(r)
    by_task = {r["task_db_id"]: r for r in all_recs}
    out = {}
    for rid, rs in by_rater.items():
        gold = [r["gold_correct"] for r in rs if r["is_gold"]]
        honey = [r["ai_conf_a"] >= AI_THRESHOLD for r in rs if r["control_type"] == "ai_honeypot"]
        anchor = [r["ai_conf_a"] <= 2 for r in rs if r["control_type"] == "human_anchor"]
        main_ab = [r["preference"] for r in rs if r["kind"] == "pairwise_pref" and r["control_type"] is None
                   and r["preference"] in ("A", "B")]
        k_left = sum(p == "A" for p in main_ab)
        rep_agree, rep_conf = [], []
        for r in rs:
            if r["control_type"] != "repeat" or r["is_repeat_of_db_id"] not in by_task:
                continue
            o = by_task[r["is_repeat_of_db_id"]]

            def chosen(x):
                p = x["preference"]
                return x["a_variant_id"] if p == "A" else x["b_variant_id"] if p == "B" else p
            rep_agree.append(chosen(r) == chosen(o))
            conf_of = lambda x: {x["a_variant_id"]: x["ai_conf_a"], x["b_variant_id"]: x["ai_conf_b"]}
            co, cr = conf_of(o), conf_of(r)
            rep_conf.append(sum(abs(co[v] - cr[v]) for v in co) / 2)
        checks = gold + honey + anchor
        mean = lambda xs: sum(xs) / len(xs) if xs else None
        q = {
            "name": rs[0]["rater_name"], "simulated": rs[0]["rater_simulated"], "n": len(rs),
            "too_fast_rate": mean([r["too_fast"] for r in rs]),
            "median_ms": percentile([r["duration_ms"] for r in rs], .5),
            "gold_acc": mean(gold), "honeypot_hit": mean(honey), "anchor_pass": mean(anchor),
            "calibration_score": mean(checks),
            "position_left_rate": k_left / len(main_ab) if main_ab else None,
            "position_p": binom_two_sided(k_left, len(main_ab)) if main_ab else None,
            "self_consistency": mean(rep_agree), "repeat_conf_diff": mean(rep_conf),
        }
        flags = []
        if q["gold_acc"] is not None and q["gold_acc"] < 0.8:
            flags.append("金标题错得多")
        if q["too_fast_rate"] is not None and q["too_fast_rate"] > 0.2:
            flags.append("答得过快")
        if q["position_p"] is not None and q["position_p"] < 0.05:
            flags.append("位置偏差")
        if q["self_consistency"] is not None and q["self_consistency"] < 0.5:
            flags.append("自洽度低")
        if q["honeypot_hit"] is not None and q["honeypot_hit"] < 0.5:
            flags.append("认不出 AI 蜜罐")
        q["flags"] = flags
        out[rid] = q
    return out


def analyze(conn, n_boot=1000, seed=0, include_too_fast=False, exclude_simulated=False, write_back=False):
    recs = records(conn)
    quality = rater_quality(recs)
    use = [r for r in recs if (include_too_fast or not r["too_fast"]) and
           not (exclude_simulated and r["rater_simulated"])]
    total_ab = [r["preference"] for r in use if r["kind"] == "pairwise_pref" and r["control_type"] is None
                and r["preference"] in ("A", "B")]
    k = sum(p == "A" for p in total_ab)
    report = {
        "settings": {"n_boot": n_boot, "seed": seed, "include_too_fast": include_too_fast,
                     "exclude_simulated": exclude_simulated},
        "n_records": len(recs), "n_used": len(use),
        "n_simulated": sum(r["rater_simulated"] for r in use),
        "n_example_items": len({r["item_id"] for r in use if r["item_is_example"]}),
        "position_bias_overall": {"left_rate": k / len(total_ab) if total_ab else None,
                                  "p": binom_two_sided(k, len(total_ab)) if total_ab else None, "n": len(total_ab)},
        "lines": [analyze_line(use, ln, n_boot, seed) for ln in ("台词", "口播")],
        "raters": quality,
    }
    if write_back:
        with conn:
            for rid, q in quality.items():
                conn.execute("UPDATE rater SET calibration_score=?, position_bias=?, self_consistency=?, "
                             "stats_updated_at=datetime('now') WHERE id=?",
                             (q["calibration_score"], q["position_left_rate"], q["self_consistency"], rid))
    return report


# ---------- 报告 ----------

def _f(x, pct=False, nd=2):
    if x is None:
        return "—"
    return f"{x * 100:.0f}%" if pct else f"{x:.{nd}f}"


def to_markdown(rep) -> str:
    L = ["# 盲审分析报告", ""]
    if rep["n_example_items"] or rep["n_simulated"]:
        L += [f"> ⚠ 含示例数据：{rep['n_example_items']} 个示例条目，{rep['n_simulated']} 条模拟评审作答。"
              "这些数字只用来演示流程，不代表任何候选的真实水平。", ""]
    s = rep["settings"]
    L += [f"作答 {rep['n_records']} 条，进入分析 {rep['n_used']} 条"
          f"（{'含' if s['include_too_fast'] else '剔除'}过快作答；bootstrap {s['n_boot']} 次，按条目抽样）。", ""]
    pb = rep["position_bias_overall"]
    L += [f"整体位置偏差：选左边（A）的比例 {_f(pb['left_rate'], True)}，n={pb['n']}，双侧二项检验 p={_f(pb['p'], nd=3)}。", ""]
    for ln in rep["lines"]:
        L += [f"## {ln['line']}", "", f"作答 {ln['n_judgments']} 条，进入 BT 的对局 {ln['n_games']} 场。", ""]
        if not ln["systems"]:
            L += ["（没有数据）", ""]
            continue
        L += ["| 系统 | BT 分 | 95% CI | 对局 | 胜率 | 对真人胜率 | 都不行 | 判别次数 | 检出率 | 检出率 95% CI | 相对位置 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        order = sorted(ln["systems"].items(), key=lambda kv: -(kv[1]["bt"] if kv[1]["bt"] is not None else -1e9))
        for name, v in order:
            ci = v["bt_ci"]
            dci = v["detection_ci"]
            L.append(f"| {name} | {_f(v['bt'], nd=0)} | {f'{ci[0]:.0f}–{ci[1]:.0f}' if ci else '—'} | {v['games']} | "
                     f"{_f(v['win_rate'], True)} | {_f(v['win_rate_vs_human'], True)} | {_f(v['both_bad_rate'], True)} | "
                     f"{v['n_ratings']} | {_f(v['detection_rate'], True)} | "
                     f"{f'{dci[0]*100:.0f}%–{dci[1]*100:.0f}%' if dci else '—'} | {_f(v['relative_to_anchors'])} |")
        L += ["", "检出率 = 判别分 ≥4 的比例；相对位置 0 = 与真人锚点相同，1 = 与 AI 蜜罐相同。", "",
              "### Krippendorff α", "", "| 维度 | α | 可比单位数 | 结论 |", "|---|---|---|---|"]
        for k, v in ln["alpha"].items():
            L.append(f"| {k} | {_f(v['alpha'], nd=3)} | {v['units']} | {v['verdict']} |")
        L += ["", "### 残留 AI 腔（每次判别平均被打的标签数）", ""]
        for name, v in order:
            if v["tags_per_rating"]:
                L.append(f"- **{name}**：" + "，".join(f"{t} {c:.2f}" for t, c in v["tags_per_rating"].items()))
        if ln["top_spans"]:
            L += ["", "划选片段（前 10）：", ""]
            for sp in ln["top_spans"][:10]:
                L.append(f"- [{sp['source']}] {sp['tag'] or '未标'} ×{sp['count']}：「{sp['text']}」")
        L.append("")
    L += ["## 评审质量", "",
          "| 评审 | 模拟 | 作答 | 过快 | 中位用时 | 金标题 | 认出蜜罐 | 锚点判人 | 校准分 | 选左比例 | 位置 p | 自洽度 | 标记 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for rid, q in rep["raters"].items():
        L.append(f"| {q['name']} | {'是' if q['simulated'] else ''} | {q['n']} | {_f(q['too_fast_rate'], True)} | "
                 f"{_f((q['median_ms'] or 0) / 1000, nd=1)}s | {_f(q['gold_acc'], True)} | {_f(q['honeypot_hit'], True)} | "
                 f"{_f(q['anchor_pass'], True)} | {_f(q['calibration_score'])} | {_f(q['position_left_rate'], True)} | "
                 f"{_f(q['position_p'], nd=3)} | {_f(q['self_consistency'], True)} | {'、'.join(q['flags'])} |")
    return "\n".join(L) + "\n"


def to_json(rep) -> str:
    return json.dumps(rep, ensure_ascii=False, indent=2, default=str)
