"""适配器基类和 skill 定位。

配置里每个角色（generator / rewriter / judge）写成：

    {"adapter": "pipeline.adapters.fake:FakeAdapter", "model": "...", "vendor": "...", "params": {...}}

runner 按点分路径找到适配器类，用 (role, model, vendor, params, slots) 实例化。
slots 是这个角色用到的槽位，例如 S3 用 {"B": {...}, "C": {...}}，每个槽位里 skills 已经解析成 SkillRef。

skill id 的写法：
- "baseline-none"：不加载任何 skill（基线）；
- "<id>"：先找 skills/variants/<id>/，再找 skills/upstream/<id>/；
- "upstream/<id>" 或 "variants/<id>"：指定目录。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..briefs import ROOT

BASELINE_NONE = "baseline-none"
SKILLS_DIR = ROOT / "skills"


class SkillNotFound(ValueError):
    pass


@dataclass(frozen=True)
class SkillRef:
    id: str
    path: Path | None          # None 表示 baseline-none

    @property
    def is_none(self) -> bool:
        return self.path is None

    def text(self) -> str:
        """skill 正文（SKILL.md）。baseline-none 或没有 SKILL.md 时返回空串。"""
        if self.path is None:
            return ""
        f = self.path / "SKILL.md"
        return f.read_text(encoding="utf-8") if f.is_file() else ""

    def to_json(self) -> dict:
        return {"id": self.id, "path": self.path.relative_to(ROOT).as_posix() if self.path else None}


def resolve_skill(spec: str, skills_dir: Path = SKILLS_DIR) -> SkillRef:
    spec = (spec or "").strip().strip("/")
    if spec == BASELINE_NONE:
        return SkillRef(BASELINE_NONE, None)
    if spec.startswith(("upstream/", "variants/")):
        candidates = [skills_dir / spec]
    else:
        candidates = [skills_dir / "variants" / spec, skills_dir / "upstream" / spec]
    for c in candidates:
        if c.is_dir():
            return SkillRef(spec, c.resolve())
    raise SkillNotFound(f"找不到 skill {spec!r}：查过 " + "、".join(str(c.relative_to(skills_dir.parent)) for c in candidates))


class ModelAdapter:
    """所有模型适配器的基类。子类实现用得到的方法即可。"""

    def __init__(self, role: str, model: str = "", vendor: str = "", params: dict | None = None,
                 slots: dict | None = None):
        self.role = role
        self.model = model
        self.vendor = vendor
        self.params = dict(params or {})
        self.slots = dict(slots or {})

    @property
    def skills(self) -> list[SkillRef]:
        return [s for slot in self.slots.values() for s in slot.get("skills", [])]

    def describe(self) -> dict:
        return {"adapter": f"{type(self).__module__}:{type(self).__name__}", "role": self.role,
                "model": self.model, "vendor": self.vendor,
                "slots": {k: {"skills": [s.id for s in v.get("skills", [])], "combine": v.get("combine")}
                          for k, v in self.slots.items()}}

    def generate(self, ctx: dict, n: int) -> list[str]:
        """S1：按 brief 生成 n 份稿件。"""
        raise NotImplementedError(f"{type(self).__name__} 不支持 generate")

    def rewrite(self, ctx: dict, hits: list[dict]) -> str:
        """S3：只改 hits 指出的位置，返回改写后的全文。"""
        raise NotImplementedError(f"{type(self).__name__} 不支持 rewrite")

    def judge(self, ctx: dict) -> dict:
        """G4：返回 {"verdict": "pass|review|rewrite", "score": float|None, "reason": str}。"""
        raise NotImplementedError(f"{type(self).__name__} 不支持 judge")
