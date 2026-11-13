"""python -m writer run --brief <brief.json> [--out <目录>] [--n 3] [--config writer/config.json]
python -m writer check --brief <brief.json>              # 只检查 brief，不写稿
python -m writer check-text --brief <brief.json> --text <稿子.txt> [--no-model]   # 检查一份现成稿子
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .core import ROOT, check_brief, check_draft, make_adapter, run


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m writer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="写稿并检查")
    r.add_argument("--brief", required=True)
    r.add_argument("--out", default=None)
    r.add_argument("--n", type=int, default=None)
    r.add_argument("--config", default=str(ROOT / "writer/config.json"))
    c = sub.add_parser("check", help="只检查 brief")
    c.add_argument("--brief", required=True)
    t = sub.add_parser("check-text", help="检查一份现成稿子")
    t.add_argument("--brief", required=True)
    t.add_argument("--text", required=True)
    t.add_argument("--config", default=str(ROOT / "writer/config.json"))
    t.add_argument("--no-model", action="store_true", help="不调用模型，跳过“多出来的内容”检查")
    a = ap.parse_args(argv)

    brief = json.loads(Path(a.brief).read_text(encoding="utf-8"))
    if a.cmd == "check":
        res = check_brief(brief)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    if a.cmd == "check-text":
        checker = None if a.no_model else make_adapter(cfg, with_skills=False)
        res = check_draft(Path(a.text).read_text(encoding="utf-8"), brief, cfg, checker=checker)
        res.pop("text")
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["pass"] else 1
    out = Path(a.out) if a.out else ROOT / "writer/out" / f"{brief.get('id', 'brief')}-{time.strftime('%m%d-%H%M')}"
    rep = run(Path(a.brief), out, cfg, a.n)
    print((out / "report.md").read_text(encoding="utf-8"))
    print(f"\n稿子和报告在：{out}")
    return 0 if rep["drafts"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
