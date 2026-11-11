"""S1 / S3 / G4 的阶段函数：从 ctx["adapter"] 取适配器（runner 按配置放进去）。

ctx 在约定字段之外多三个：
    adapter        这一阶段用的 ModelAdapter 实例
    rewrite_hits   S3 要处理的命中（来自 S2，或打回它的 G2 / G3）
    rewrite_from   这些命中来自哪个阶段
"""
from __future__ import annotations

from ..contract import result


def generate(ctx: dict) -> dict:
    """S1：生成 N 份。配置参数 n，默认 3。"""
    ad = ctx["adapter"]
    n = int((ctx.get("config") or {}).get("n", 3))
    texts = ad.generate(ctx, n)
    return result("S1", "slot", "pass", None, [], {"n": len(texts), **ad.describe()}, texts=list(texts))


def rewrite(ctx: dict) -> dict:
    """S3：只改命中处；没命中就原样放行，不调用模型。"""
    ad = ctx["adapter"]
    hits = [h for h in (ctx.get("rewrite_hits") or []) if h.get("severity") != "hint"]
    if not hits:
        return result("S3", "slot", "pass", None, [], {"changed": False, "called_model": False,
                                                        "from": ctx.get("rewrite_from"), **ad.describe()},
                      text=ctx["text"])
    new = ad.rewrite(ctx, hits)
    return result("S3", "slot", "pass", None, [], {"changed": new != ctx["text"], "called_model": True,
                                                    "from": ctx.get("rewrite_from"), "targets": len(hits),
                                                    **ad.describe()}, text=new)


def judge(ctx: dict) -> dict:
    """G4 LLM 裁判（软）。

    配置参数 pass_at / rewrite_below 是阈值；校准前（任一为 null）只记录分数，一律转人工。
    """
    ad = ctx["adapter"]
    cfg = ctx.get("config") or {}
    out = ad.judge(ctx)
    score = out.get("score")
    pass_at, rewrite_below = cfg.get("pass_at"), cfg.get("rewrite_below")
    metrics = {"score": score, "judge_verdict": out.get("verdict"), "reason": out.get("reason", ""),
               "calibrated": pass_at is not None and rewrite_below is not None, **ad.describe()}
    if not metrics["calibrated"] or score is None:
        return result("G4", "soft", "review", "human", [], metrics)
    if score >= pass_at:
        return result("G4", "soft", "pass", None, [], metrics)
    if score < rewrite_below:
        return result("G4", "soft", "route", "S3", [], metrics)
    return result("G4", "soft", "review", "human", [], metrics)
