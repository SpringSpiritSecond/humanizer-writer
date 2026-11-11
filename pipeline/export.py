"""把运行报告导出成 `python -m workbench import` 能读的 JSON：

    {"items": [<brief>, ...], "variants": [{item_id, text, source_type, candidate_id,
                                            skill_git_hash, model, params, sample_idx}, ...]}

只导第一层存活（layer1.survived）的稿件；--exclude-review 时再去掉要人工复核的。
params 里带上配置名、最终状态、轮次和复核原因，工作台管理页能看到，评审看不到。
"""
from __future__ import annotations


def _model_label(rep: dict) -> str:
    models = (rep.get("config") or {}).get("models") or {}
    parts = [f"{role}={m.get('model')}" for role, m in models.items() if isinstance(m, dict) and m.get("model")]
    return "; ".join(parts)


def to_workbench(reports: list[dict], exclude_review: bool = False) -> dict:
    items: dict[str, dict] = {}
    variants = []
    skipped = []
    for rep in reports:
        if rep.get("kind") != "pipeline_run":
            raise ValueError("不是 pipeline run 的报告")
        brief = rep.get("brief") or {}
        if rep.get("status") == "brief_returned":
            skipped.append({"brief_id": rep.get("brief_id"), "reason": "brief 被 S0 退回"})
            continue
        cand = rep.get("candidate") or {}
        cfg = rep.get("config") or {}
        kept = 0
        for d in rep.get("drafts", []):
            if not d["layer1"]["survived"]:
                skipped.append({"draft_id": d["draft_id"], "reason": f"第一层淘汰（{d['layer1']['eliminated_by']}）"})
                continue
            if exclude_review and d["status"] == "human":
                skipped.append({"draft_id": d["draft_id"], "reason": "要人工复核，按 --exclude-review 跳过"})
                continue
            v = {
                "item_id": brief["id"],
                "text": d["text_final"],
                "source_type": cand.get("source_type") or "candidate",
                "skill_git_hash": cfg.get("git_hash") or rep.get("pipeline_git_hash") or "",
                "model": _model_label(rep),
                "params": {"pipeline_config": cfg.get("name"), "status": d["status"], "rounds": d["rounds"],
                           "needs_review": d["needs_review"], "pipeline_git_hash": rep.get("pipeline_git_hash"),
                           "draft_id": d["draft_id"]},
                "sample_idx": d["sample_idx"],
            }
            if v["source_type"] == "candidate":
                v["candidate_id"] = cand.get("candidate_id") or cfg.get("name")
            variants.append(v)
            kept += 1
        if kept:
            items[brief["id"]] = brief
    out = {"items": list(items.values()), "variants": variants}
    if items and all(b.get("is_example") for b in items.values()):
        out["is_example"] = True
        out["_说明"] = "示例数据：由 pipeline 示例 brief 和示例稿件导出，不是真实作品。"
    out["_skipped"] = skipped
    return out
