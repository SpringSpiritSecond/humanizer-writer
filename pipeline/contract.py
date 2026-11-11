"""docs/工作流编排.md 3.1 的阶段结果约定，以及校验。

在约定之外，本包额外用到了这些东西（PR 里有说明）：
- kind="slot"：S1 / S3 这类槽位阶段不是闸门，约定的四种 kind 都不贴切；
- S1 结果带 "texts"（生成的多份稿件），S3 结果带 "text"（改写后的稿件）；
- hit 的 span 可以是 None，表示针对全文的问题（长度、缺字段），没有具体位置；
- 闸门自己的规则 id 加 "g0." / "g1." / "g2." / "s0." 前缀，避免和 3.2 的风格规则 id 混用。
"""
from __future__ import annotations

ORDER = ["S0", "S1", "G0", "S2", "S3", "G1", "G2", "G3", "G4", "G5"]
KINDS = {"hard", "soft", "report", "monitor", "slot"}
VERDICTS = {"pass", "fail", "route", "review"}
ROUTES = {"S3", "human", None}
SEVERITIES = {"block", "warn", "hint"}


class StageContractError(ValueError):
    pass


def result(stage: str, kind: str, verdict: str = "pass", route_to=None, hits=None, metrics=None, **extra) -> dict:
    out = {"stage": stage, "kind": kind, "verdict": verdict, "route_to": route_to,
           "hits": list(hits or []), "metrics": dict(metrics or {})}
    out.update(extra)
    return out


def hit(rule: str, message: str, severity: str = "block", span=None, excerpt: str = "", **extra) -> dict:
    out = {"rule": rule, "span": list(span) if span is not None else None, "excerpt": excerpt,
           "severity": severity, "message": message}
    out.update(extra)
    return out


def validate(res, stage: str) -> dict:
    """阶段返回值不合约定就报错，并指明是哪个阶段。"""
    def bad(msg):
        raise StageContractError(f"{stage} 的返回值不符合接口约定：{msg}")

    if not isinstance(res, dict):
        bad(f"应返回 dict，实际是 {type(res).__name__}")
    for k in ("stage", "kind", "verdict", "hits", "metrics"):
        if k not in res:
            bad(f"缺字段 {k}")
    res.setdefault("route_to", None)
    if res["kind"] not in KINDS:
        bad(f"kind={res['kind']!r}")
    if res["verdict"] not in VERDICTS:
        bad(f"verdict={res['verdict']!r}")
    if res["route_to"] not in ROUTES:
        bad(f"route_to={res['route_to']!r}")
    if res["verdict"] == "route" and res["route_to"] is None:
        bad("verdict=route 时必须给 route_to")
    if not isinstance(res["hits"], list) or not isinstance(res["metrics"], dict):
        bad("hits 应是 list，metrics 应是 dict")
    for h in res["hits"]:
        if not isinstance(h, dict) or "rule" not in h or "severity" not in h:
            bad(f"hit 缺 rule 或 severity：{h!r}")
        if h["severity"] not in SEVERITIES:
            bad(f"hit 的 severity={h['severity']!r}")
        span = h.get("span")
        if span is not None and not (isinstance(span, (list, tuple)) and len(span) == 2
                                     and all(isinstance(x, int) for x in span) and span[0] <= span[1]):
            bad(f"hit 的 span={span!r}，应是 [起, 止) 两个整数")
    return res
