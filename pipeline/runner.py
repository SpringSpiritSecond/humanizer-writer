"""runner：按 S0 → S1 → G0 → S2 → S3 → G1 → G2 → G3 → G4 → G5 跑一份 brief 下的所有稿件。

轮次控制
- 第 0 轮：S3 处理 S2 的命中（没有命中就原样放行）。
- G2 或 G3 打回 S3（verdict=route, route_to=S3）时，轮次 +1，S3 只改打回的命中，然后重跑 G1、G2（G3 再跑一遍）。
- 轮次达到槽位 D 的 max_rounds，或者配置里没有 S3，就不再回流，转人工。

每份稿件的最终状态 status：
    passed       全部放行
    eliminated   被硬闸门拦下（G0 / G1 fail）
    human        要人看：G1 豁免区或模糊区、轮数用完、软闸门转人工
brief 被 S0 退回时整份报告 status=brief_returned，没有稿件。

layer1 是评测的第一层淘汰：G0–G2 里有硬拦，或 G2 的问题到最后都没修好，survived=false。
导出到工作台时只导 survived=true 的稿件。
"""
from __future__ import annotations

import datetime as _dt
import subprocess

from .briefs import ROOT
from .config import Config
from .contract import validate
from .textutil import normalize

LOOP_GATES = ("G1", "G2", "G3")
HARD_LAYER1 = ("G0", "G1", "G2")


class RunnerError(RuntimeError):
    pass


def git_hash() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


class _Draft:
    def __init__(self, runner: "Runner", idx: int, text: str, source: str, base_history: list):
        self.r = runner
        self.idx = idx
        self.text = text
        self.text_initial = text
        self.source = source
        self.round = 0
        self.history = list(base_history)
        self.log: list[dict] = []
        self.needs_review: list[dict] = []
        self.eliminated_by: str | None = None
        self.layer1_by: str | None = None
        self.stopped = False

    # -- 调用一个阶段 --
    def call(self, name: str, **extra) -> dict | None:
        st = self.r.cfg.stages.get(name)
        if st is None or name in self.r.skip:
            return None
        ctx = {"line": self.r.cfg.line, "brief": self.r.brief, "profile": self.r.cfg.profile,
               "text": self.text, "round": self.round, "history": list(self.history),
               "batch_texts": [d.text for d in self.r.drafts if d is not self], "config": dict(st.params)}
        if st.adapter is not None:
            ctx["adapter"] = st.adapter
        ctx.update(extra)
        res = validate(st.fn(ctx), name)
        res = dict(res)
        res["round"] = self.round
        if name == "S3" and isinstance(res.get("text"), str):
            self.text = normalize(res["text"], self.r.cfg.line)
        self.history.append(res)
        self.log.append(res)
        return res

    def can_reroute(self) -> bool:
        return "S3" in self.r.cfg.stages and "S3" not in self.r.skip and self.round < self.r.cfg.max_rounds

    def flag(self, stage: str, reason: str):
        if any(x["stage"] == stage and x["reason"] == reason for x in self.needs_review):
            return                      # 每轮重跑 G1 会得到同样的复核结论，只记一次
        self.needs_review.append({"stage": stage, "round": self.round, "reason": reason})

    def settle(self, res: dict | None) -> str:
        """处理一个闸门的结果。返回 "ok" / "stop" / "reroute"。"""
        if res is None:
            return "ok"
        v, stage, kind = res["verdict"], res["stage"], res["kind"]
        if v == "pass":
            return "ok"
        if v == "fail":
            if kind == "hard":
                self.eliminated_by = stage
                if stage in HARD_LAYER1:
                    self.layer1_by = stage
                return "stop"
            self.flag(stage, "软闸门不该硬拦，按转人工处理")
            return "ok"
        if v == "route" and res["route_to"] == "S3":
            if stage in ("G2", "G3"):
                if self.can_reroute():
                    return "reroute"
                why = "配置里没有 S3，不能回流" if "S3" not in self.r.cfg.stages or "S3" in self.r.skip \
                    else f"改写轮数已到上限 {self.r.cfg.max_rounds}"
                self.flag(stage, f"{why}，转人工")
                if stage == "G2":           # 硬闸门的问题没修好：评测里算第一层淘汰，生产里转人工
                    self.layer1_by = "G2"
                    return "stop"
                return "ok"
            self.flag(stage, "建议重写；第一期只有 G2、G3 自动回流，转人工")
            return "ok"
        # review，或 route 到 human
        self.flag(stage, "转人工复核" if v == "review" else "打回人工")
        return "ok"

    def rewrite(self, hits: list[dict], source: str):
        self.call("S3", rewrite_hits=hits, rewrite_from=source)

    def run(self):
        if self.settle(self.call("G0")) == "stop":
            return
        s2 = self.call("S2")
        self.rewrite(s2["hits"] if s2 else [], "S2")
        while True:
            again = False
            for gate in LOOP_GATES:
                res = self.call(gate)
                out = self.settle(res)
                if out == "stop":
                    return
                if out == "reroute":
                    self.round += 1
                    self.rewrite(res["hits"], gate)
                    again = True
                    break
            if not again:
                break
        self.settle(self.call("G4"))
        self.call("G5")

    def report(self) -> dict:
        if self.eliminated_by:
            status = "eliminated"
        elif self.needs_review:
            status = "human"
        else:
            status = "passed"
        return {
            "draft_id": f"{self.r.brief.get('id')}#{self.idx}",
            "sample_idx": self.idx,
            "source": self.source,
            "status": status,
            "rounds": self.round,
            "layer1": {"survived": self.layer1_by is None, "eliminated_by": self.layer1_by},
            "needs_review": self.needs_review,
            "text_initial": self.text_initial,
            "text_final": self.text,
            "stages": self.log,
        }


class Runner:
    def __init__(self, cfg: Config, brief: dict, skip=()):
        self.cfg = cfg
        self.brief = brief
        self.skip = set(skip)
        self.drafts: list[_Draft] = []

    def run(self, texts: list[str] | None = None, sources: list[str] | None = None) -> dict:
        cfg = self.cfg
        rep = {
            "kind": "pipeline_run",
            "created_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "pipeline_git_hash": git_hash(),
            "config": cfg.describe(),
            "candidate": cfg.candidate,
            "line": cfg.line,
            "brief_id": self.brief.get("id") if isinstance(self.brief, dict) else None,
            "brief": self.brief,
            "skipped_stages": sorted(self.skip),
            "warnings": list(cfg.warnings),
            "status": "ok",
            "brief_check": None,
            "generation": None,
            "drafts": [],
        }
        base_history = []
        s0 = cfg.stages.get("S0")
        if s0 and "S0" not in self.skip:
            res = validate(s0.fn({"line": cfg.line, "brief": self.brief, "profile": cfg.profile, "text": "",
                                  "round": 0, "history": [], "batch_texts": [], "config": dict(s0.params)}), "S0")
            res = dict(res, round=0)
            rep["brief_check"] = res
            base_history.append(res)
            if res["verdict"] == "fail":
                rep["status"] = "brief_returned"
                return rep
        if texts is None:
            s1 = cfg.stages.get("S1")
            if s1 is None or "S1" in self.skip:
                raise RunnerError("没有给稿件，配置里也没有可用的 S1")
            res = validate(s1.fn({"line": cfg.line, "brief": self.brief, "profile": cfg.profile, "text": "",
                                  "round": 0, "history": list(base_history), "batch_texts": [],
                                  "config": dict(s1.params), "adapter": s1.adapter}), "S1")
            res = dict(res, round=0)
            texts = list(res.get("texts") or [])
            if not texts:
                raise RunnerError("S1 没有生成任何稿件")
            rep["generation"] = res
            base_history.append({k: v for k, v in res.items() if k != "texts"})
            sources = [f"S1#{i}" for i in range(len(texts))]
        sources = sources or [f"input#{i}" for i in range(len(texts))]
        self.drafts = [_Draft(self, i, normalize(t, cfg.line), sources[i], base_history) for i, t in enumerate(texts)]
        for d in self.drafts:
            d.run()
        rep["drafts"] = [d.report() for d in self.drafts]
        return rep


def run_brief(cfg: Config, brief: dict, texts: list[str] | None = None, sources=None, skip=()) -> dict:
    return Runner(cfg, brief, skip).run(texts, sources)
