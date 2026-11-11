"""流水线入口。配置里写 "S2": "detect.stages:s2"、"G3": "detect.stages:g3"。

两个函数都按 docs/工作流编排.md 3.1 节的约定收 ctx、返回结果 dict。
"""
from __future__ import annotations

from . import g3 as _g3
from . import s2 as _s2


def s2(ctx: dict) -> dict:
    """S2 规则检测：只报告命中位置，verdict 恒为 pass。"""
    return _s2.run(ctx)


def g3(ctx: dict) -> dict:
    """G3 风格计量：没给阈值时只记录；超标且规则为 on 时 route 到 S3。"""
    return _g3.run(ctx)


