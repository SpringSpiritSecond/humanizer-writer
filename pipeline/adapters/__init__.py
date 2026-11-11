"""模型适配器：S1 生成、S3 改写、G4 裁判共用的可插拔接口。

这一期只有测试用的假适配器（fake.FakeAdapter），不接任何真实 API。
"""
from .base import BASELINE_NONE, ModelAdapter, SkillRef, resolve_skill

__all__ = ["BASELINE_NONE", "ModelAdapter", "SkillRef", "resolve_skill"]
