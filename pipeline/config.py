"""读 configs/<名字>.json：线、profile、各角色的模型、槽位 A–D、各阶段的点分路径和参数。

阶段写法（三种都行，null 或不写表示跳过）：
    "G2": "pipeline.gates.fidelity:run"
    "G2": {"path": "pipeline.gates.fidelity:run", "params": {...}}
    "G2": <可调用对象>                      （只在测试里直接传 dict 时用）
点分路径里没有冒号时取模块的 run。

模型阶段默认的角色和槽位：S1 → generator + 槽位 A；S3 → rewriter + 槽位 B、C；G4 → judge。
可以在阶段里用 "role" / "slots" 覆盖。槽位 D 的 max_rounds 是改写轮数上限。
"""
from __future__ import annotations

import copy
import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .adapters.base import ModelAdapter, SkillNotFound, resolve_skill
from .briefs import ROOT
from .contract import ORDER

MODEL_STAGES = {"S1": ("generator", ["A"]), "S3": ("rewriter", ["B", "C"]), "G4": ("judge", [])}
DEFAULT_MAX_ROUNDS = 2


class ConfigError(ValueError):
    pass


@dataclass
class Stage:
    name: str
    fn: object
    path: str
    params: dict = field(default_factory=dict)
    adapter: ModelAdapter | None = None


@dataclass
class Config:
    name: str
    line: str
    profile: dict
    raw: dict
    stages: dict
    max_rounds: int
    source_path: str | None = None
    warnings: list = field(default_factory=list)

    @property
    def candidate(self) -> dict:
        c = self.raw.get("candidate") or {}
        return {"source_type": c.get("source_type") or "candidate",
                "candidate_id": c.get("candidate_id") or self.name}

    def describe(self) -> dict:
        return {"name": self.name, "line": self.line, "path": self.source_path,
                "git_hash": self.raw.get("git_hash"), "max_rounds": self.max_rounds,
                "stages": {k: s.path for k, s in self.stages.items()},
                "slots": self.raw.get("slots"), "models": self.raw.get("models")}


def _resolve_path(p: str | Path, base: Path | None = None) -> Path:
    p = Path(p)
    if p.is_absolute():
        return p
    for root in ([base] if base else []) + [ROOT, Path.cwd()]:
        if (root / p).exists():
            return root / p
    return ROOT / p


def load_object(spec: str):
    """"pkg.mod:attr" → 对象；没有冒号时取 run。"""
    mod, _, attr = spec.partition(":")
    try:
        m = importlib.import_module(mod)
    except ImportError as e:
        raise ConfigError(f"导入不了阶段模块 {mod!r}（{spec}）：{e}") from e
    try:
        return getattr(m, attr or "run")
    except AttributeError as e:
        raise ConfigError(f"模块 {mod!r} 里没有 {attr or 'run'!r}（{spec}）") from e


def _slot(raw_slots: dict, key: str) -> dict:
    s = copy.deepcopy(raw_slots.get(key) or {})
    try:
        s["skills"] = [resolve_skill(x) for x in s.get("skills", [])]
    except SkillNotFound as e:
        raise ConfigError(f"槽位 {key}：{e}") from e
    s.setdefault("combine", "serial")
    return s


def build_adapter(raw: dict, role: str, slot_keys: list[str]) -> ModelAdapter:
    models = raw.get("models") or {}
    rc = models.get(role)
    if not rc or not rc.get("adapter"):
        raise ConfigError(f"models.{role}.adapter 没填，模型阶段用不了")
    cls = load_object(rc["adapter"])
    if not (isinstance(cls, type) and issubclass(cls, ModelAdapter)):
        raise ConfigError(f"{rc['adapter']} 不是 ModelAdapter 的子类")
    slots = {k: _slot(raw.get("slots") or {}, k) for k in slot_keys}
    return cls(role, rc.get("model", ""), rc.get("vendor", ""), rc.get("params") or {}, slots)


def from_dict(raw: dict, source_path: str | None = None, base: Path | None = None) -> Config:
    line = raw.get("line")
    if line not in ("台词", "口播"):
        raise ConfigError(f"line 应是 台词 或 口播，实际是 {line!r}")
    prof_path = _resolve_path(raw.get("profile") or f"profiles/{line}.json", base)
    try:
        profile = json.loads(prof_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ConfigError(f"读不了 profile {prof_path}：{e}") from e
    if profile.get("line") != line:
        raise ConfigError(f"profile {prof_path.name} 的 line 是 {profile.get('line')!r}，配置是 {line}")
    warnings = []
    unknown = {k for k in (raw.get("stages") or {}) if not k.startswith("_")} - set(ORDER)
    if unknown:
        warnings.append(f"不认识的阶段，忽略：{sorted(unknown)}")
    stages = {}
    for name in ORDER:
        spec = (raw.get("stages") or {}).get(name)
        if spec is None:
            continue
        if isinstance(spec, str):
            spec = {"path": spec}
        elif callable(spec):
            spec = {"path": spec}
        if not isinstance(spec, dict) or not spec.get("path"):
            raise ConfigError(f"阶段 {name} 的写法不对：{spec!r}")
        p = spec["path"]
        fn = p if callable(p) else load_object(p)
        if not callable(fn):
            raise ConfigError(f"阶段 {name} 的 {p} 不能调用")
        adapter = None
        if name in MODEL_STAGES:
            role, slot_keys = MODEL_STAGES[name]
            adapter = build_adapter(raw, spec.get("role", role), spec.get("slots", slot_keys))
        stages[name] = Stage(name, fn, p if isinstance(p, str) else getattr(p, "__qualname__", repr(p)),
                             dict(spec.get("params") or {}), adapter)
    d = (raw.get("slots") or {}).get("D") or {}
    max_rounds = d.get("max_rounds", DEFAULT_MAX_ROUNDS)
    if not isinstance(max_rounds, int) or max_rounds < 0:
        raise ConfigError(f"slots.D.max_rounds 应是非负整数，实际是 {max_rounds!r}")
    if "max_rounds" not in d:
        warnings.append(f"slots.D.max_rounds 没填，按 {DEFAULT_MAX_ROUNDS} 轮")
    # 编排规则 1：裁判换一家厂商
    models = raw.get("models") or {}
    jv = (models.get("judge") or {}).get("vendor")
    if "G4" in stages and jv and jv in {(models.get(r) or {}).get("vendor") for r in ("generator", "rewriter")}:
        warnings.append(f"G4 裁判和写稿模型是同一家厂商（{jv}），违反“skill 不给自己当裁判”")
    return Config(raw.get("name") or (Path(source_path).stem if source_path else "unnamed"), line, profile,
                  raw, stages, max_rounds, source_path, warnings)


def load(path: str | Path) -> Config:
    p = _resolve_path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except OSError as e:
        raise ConfigError(f"读不了配置 {path}：{e}") from e
    except ValueError as e:
        raise ConfigError(f"配置 {path} 不是合法 JSON：{e}") from e
    try:
        rel = p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        rel = str(p)
    return from_dict(raw, rel, p.parent)
