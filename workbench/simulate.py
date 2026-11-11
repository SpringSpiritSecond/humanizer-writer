"""模拟评审作答，只用来在没有真人评审时演示和测试 导出 → 分析 这一段。

模拟评审在 rater 表里 is_simulated=1，导出和报告都会标出来。模拟器直接读揭盲表来
决定“打几分”，所以它的结果对候选好坏没有任何意义。
"""
from __future__ import annotations

import json
import math
import random

from . import service

# 示例里各来源的“真实”质量和 AI 感（随手设定，只为让演示数据有点结构）
QUALITY = {"human": 0.8, "示例候选-甲": 0.9, "oneline_baseline": 0.3, "示例候选-乙": -0.3,
           "raw_ai_baseline": -0.9, "gold_bad": -3.0}
AINESS = {"human": 1.8, "示例候选-甲": 2.2, "oneline_baseline": 3.0, "示例候选-乙": 3.4,
          "raw_ai_baseline": 4.4, "gold_bad": 4.0}
TAG_BY_SOURCE = {"raw_ai_baseline": ["套话", "不像人说话"], "示例候选-乙": ["电报体"],
                 "oneline_baseline": ["节奏单一"], "gold_bad": ["套话"]}


def simulate(conn, rater_id: int, seed: int = 0, noise: float = 0.8, left_bias: float = 0.0,
             fast_rate: float = 0.05) -> int:
    rng = random.Random(seed * 7919 + rater_id)
    rows = conn.execute(
        "SELECT t.public_id, t.kind, sa.source_label la, sb.source_label lb, va.char_len ca, vb.char_len cb "
        "FROM task t JOIN variant_source sa ON sa.variant_id=t.left_variant_id "
        "JOIN variant va ON va.id=t.left_variant_id "
        "LEFT JOIN variant_source sb ON sb.variant_id=t.right_variant_id "
        "LEFT JOIN variant vb ON vb.id=t.right_variant_id "
        "LEFT JOIN judgment j ON j.task_id=t.id WHERE t.rater_id=? AND j.id IS NULL ORDER BY t.batch_id, t.display_order",
        (rater_id,)).fetchall()

    def conf(label):
        x = AINESS.get(label, 3.0) + rng.gauss(0, noise)
        return max(1, min(5, round(x)))

    def tags(label):
        return [t for t in TAG_BY_SOURCE.get(label, []) if rng.random() < 0.5]

    n = 0
    for r in rows:
        chars = (r["ca"] or 0) + (r["cb"] or 0)
        dur = int(rng.uniform(1500, 3500)) if rng.random() < fast_rate else int(chars * rng.uniform(250, 500) + 4000)
        body = {"ai_conf_a": conf(r["la"]), "duration_ms": dur, "tags": {"A": tags(r["la"])}, "reason": "（模拟作答）"}
        if r["kind"] == "pairwise_pref":
            body["ai_conf_b"] = conf(r["lb"])
            body["tags"]["B"] = tags(r["lb"])
            d = QUALITY.get(r["la"], 0) - QUALITY.get(r["lb"], 0) + left_bias + rng.gauss(0, noise)
            qa, qb = QUALITY.get(r["la"], 0), QUALITY.get(r["lb"], 0)
            if max(qa, qb) < -0.5 and rng.random() < 0.5:
                body["preference"] = "both_bad"
            elif abs(d) < 0.25:
                body["preference"] = "tie"
            else:
                body["preference"] = "A" if rng.random() < 1 / (1 + math.exp(-2.5 * d)) else "B"
        service.submit_judgment(conn, rater_id, r["public_id"], body)
        n += 1
    return n


def ensure_sim_rater(conn, name: str) -> int:
    r = conn.execute("SELECT id FROM rater WHERE name=? AND is_simulated=1", (name,)).fetchone()
    if r:
        return r["id"]
    return service.create_rater(conn, name, "模拟评审（演示用）", simulated=True)["id"]


__all__ = ["simulate", "ensure_sim_rater", "json"]
