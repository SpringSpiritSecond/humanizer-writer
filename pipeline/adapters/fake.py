"""测试用的假适配器：按脚本返回固定文本，不调用任何模型。

params：
    script       {"generate": [...], "rewrite": [...], "judge": [...]}，按调用顺序依次取用
    script_file  同样结构的 JSON 文件（相对仓库根目录），和 script 二选一

- generate 的每一项是一份稿件；不够 n 份时循环使用；没给就报错。
- rewrite 的每一项可以是全文字符串，也可以是 {"replace": [["旧", "新"], ...]}，在当前稿件上替换；
  用完或没给时原样返回（相当于“没改”）。
- judge 的每一项是 {"verdict", "score", "reason"}；用完后重复最后一项；没给时返回 review、score=None。
"""
from __future__ import annotations

import json

from ..briefs import ROOT
from .base import ModelAdapter


class FakeAdapter(ModelAdapter):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        script = self.params.get("script")
        if script is None and self.params.get("script_file"):
            script = json.loads((ROOT / self.params["script_file"]).read_text(encoding="utf-8"))
        self.script = script or {}
        self.calls: list[tuple[str, dict]] = []
        self._i = {"generate": 0, "rewrite": 0, "judge": 0}

    def _next(self, kind: str):
        items = self.script.get(kind) or []
        i = self._i[kind]
        self._i[kind] += 1
        return items[i] if i < len(items) else None

    def generate(self, ctx, n):
        items = self.script.get("generate") or []
        if not items:
            raise ValueError("FakeAdapter 没有 generate 脚本")
        self.calls.append(("generate", {"n": n}))
        return [items[k % len(items)] for k in range(n)]

    def rewrite(self, ctx, hits):
        self.calls.append(("rewrite", {"round": ctx.get("round"), "rules": [h.get("rule") for h in hits]}))
        step = self._next("rewrite")
        if step is None:
            return ctx["text"]
        if isinstance(step, str):
            return step
        text = ctx["text"]
        for old, new in step.get("replace", []):
            text = text.replace(old, new)
        return text

    def judge(self, ctx):
        self.calls.append(("judge", {}))
        items = self.script.get("judge") or []
        step = self._next("judge")
        if step is None:
            step = items[-1] if items else {"verdict": "review", "score": None, "reason": "假适配器没有裁判脚本"}
        return dict(step)
