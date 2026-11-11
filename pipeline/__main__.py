"""命令行入口：python -m pipeline <命令>

    run      跑一份 brief：
               python -m pipeline run --config configs/口播-baseline-none.json \\
                   --brief pipeline/examples/briefs/vo-example-01.json \\
                   --text-file pipeline/examples/drafts/vo-example-01_通过.txt --out report.json
             给了 --text-file 就不跑 S1，直接拿现成稿件过闸门；--gates-only 再跳过 S3、G4（完全不碰模型适配器）。
    export   把一份或多份运行报告导出成 `python -m workbench import` 能读的 JSON：
               python -m pipeline export report.json --out for_workbench.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config as cfgmod
from .contract import ORDER
from .export import to_workbench
from .runner import RunnerError, run_brief

MODEL_STAGES = ("S1", "S3", "G4")


def _read_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write(obj, out: str | None):
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(s + "\n", encoding="utf-8")
    else:
        print(s)


def _summary(rep: dict) -> str:
    lines = [f"brief {rep['brief_id']}（{rep['line']}，配置 {rep['config']['name']}）：{rep['status']}"]
    for w in rep.get("warnings", []):
        lines.append(f"  注意：{w}")
    if rep["status"] == "brief_returned":
        for h in rep["brief_check"]["hits"]:
            if h["severity"] == "block":
                lines.append(f"  退回：{h['message']}")
    for d in rep["drafts"]:
        lines.append(f"  {d['draft_id']} [{d['source']}] → {d['status']}，轮次 {d['rounds']}，"
                     f"第一层{'存活' if d['layer1']['survived'] else '淘汰（' + str(d['layer1']['eliminated_by']) + '）'}")
        for st in d["stages"]:
            bad = [h for h in st["hits"] if h["severity"] in ("block", "warn")]
            if st["verdict"] != "pass" or bad:
                lines.append(f"    {st['stage']}（第 {st['round']} 轮）{st['verdict']}")
                for h in bad[:6]:
                    lines.append(f"      - [{h['severity']}] {h['message']}")
        for r in d["needs_review"]:
            lines.append(f"    转人工：{r['stage']} {r['reason']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m pipeline", description="去 AI 味工作流：骨架与硬闸门")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="跑一份 brief")
    p.add_argument("--config", required=True)
    p.add_argument("--brief", required=True, help="brief JSON 文件")
    p.add_argument("--text-file", action="append", default=[], help="现成稿件，可以给多次；不给就用 S1 生成")
    p.add_argument("--gates-only", action="store_true", help="跳过所有模型阶段（S1、S3、G4）")
    p.add_argument("--skip", nargs="*", default=[], choices=ORDER, help="另外跳过这些阶段")
    p.add_argument("--out", help="报告写到这个文件；不给就打印到标准输出")
    p = sub.add_parser("export", help="导出成工作台导入格式")
    p.add_argument("reports", nargs="+")
    p.add_argument("--out", help="不给就打印到标准输出")
    p.add_argument("--exclude-review", action="store_true", help="要人工复核的稿件也不导")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        try:
            cfg = cfgmod.load(a.config)
        except cfgmod.ConfigError as e:
            print(f"配置错误：{e}", file=sys.stderr)
            return 2
        brief = _read_json(a.brief)
        texts = [Path(f).read_text(encoding="utf-8-sig") for f in a.text_file] or None
        sources = [f"file:{Path(f).as_posix()}" for f in a.text_file] or None
        skip = set(a.skip) | (set(MODEL_STAGES) if a.gates_only else set())
        try:
            rep = run_brief(cfg, brief, texts, sources, skip)
        except (RunnerError, cfgmod.ConfigError) as e:
            print(f"运行失败：{e}", file=sys.stderr)
            return 2
        _write(rep, a.out)
        print(_summary(rep), file=sys.stderr)
        return 3 if rep["status"] == "brief_returned" else 0

    if a.cmd == "export":
        reports = []
        for f in a.reports:
            data = _read_json(f)
            reports.extend(data if isinstance(data, list) else [data])
        out = to_workbench(reports, exclude_review=a.exclude_review)
        _write(out, a.out)
        print(f"导出 {len(out['items'])} 个 brief、{len(out['variants'])} 份稿件；跳过 {len(out['_skipped'])} 份",
              file=sys.stderr)
        for s in out["_skipped"]:
            print(f"  跳过 {s.get('draft_id') or s.get('brief_id')}：{s['reason']}", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
