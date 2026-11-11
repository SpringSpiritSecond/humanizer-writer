"""命令行入口：python -m workbench <命令>

    seed                 导入示例数据（明确标为示例），并建一个演示评审
    import <文件>         导入 brief/variant（.json）或 variant（.csv）
    rater <名字>          新建评审，打印评审码
    batch                生成一个批次（见 --help）
    serve                启动本机服务
    simulate             让模拟评审把未答的题答完（只用于演示）
    export               导出 CSV / JSONL / 偏好格式
    analyze              生成分析报告（Markdown + JSON）
    status               看进度

全局参数 --db 指定数据库文件，默认 workbench/data/workbench.sqlite3（也可用环境变量 WB_DB）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import analysis, batching, exporter, importer, service, simulate
from .db import connect

SEED_DIR = Path(__file__).resolve().parent / "seed"


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m workbench", description="中文台词/口播盲审工作台")
    ap.add_argument("--db", default=None, help="SQLite 文件路径")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="导入示例数据")
    p = sub.add_parser("import", help="导入 JSON / CSV")
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("rater", help="新建评审")
    p.add_argument("name")
    p.add_argument("--expertise", default="")
    p = sub.add_parser("batch", help="生成批次")
    p.add_argument("--rater", type=int, required=True, help="评审 id")
    p.add_argument("--line", choices=["台词", "口播"], required=True)
    p.add_argument("--pairs", type=int, default=24, help="正式两两题数")
    p.add_argument("--singles", type=int, default=4, help="正式单篇判别题数")
    p.add_argument("--sources", nargs="*", help="只比较这些来源（source_label），默认全部")
    p.add_argument("--control-ratio", type=float, default=batching.CONTROL_TARGET)
    p.add_argument("--max-len-ratio", type=float, default=1.5, help="两篇长度比超过这个值就不配对")
    p.add_argument("--seed", type=int)
    p = sub.add_parser("serve", help="启动服务")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--admin-token")
    p = sub.add_parser("simulate", help="模拟评审作答（演示用）")
    p.add_argument("--raters", type=int, default=3, help="模拟评审人数")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--pairs", type=int, default=20)
    p = sub.add_parser("export", help="导出")
    p.add_argument("--out", default="workbench/data/export")
    p.add_argument("--include-simulated", action="store_true", help="偏好格式里也放模拟评审的作答")
    p = sub.add_parser("analyze", help="分析")
    p.add_argument("--out", default="workbench/data/export")
    p.add_argument("--boot", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--include-too-fast", action="store_true")
    p.add_argument("--exclude-simulated", action="store_true")
    p.add_argument("--write-back", action="store_true", help="把校准分、位置偏差、自洽度写回 rater 表")
    sub.add_parser("status", help="看进度")
    a = ap.parse_args(argv)
    conn = connect(a.db)

    if a.cmd == "seed":
        if conn.execute("SELECT 1 FROM item WHERE id LIKE '%-demo-%' LIMIT 1").fetchone():
            print("示例数据已经导入过了。要重来请删掉数据库文件。")
        else:
            for f in ("示例_briefs与稿件.json", "示例_候选稿.csv"):
                print(f, importer.import_path(conn, SEED_DIR / f))
        r = conn.execute("SELECT id, code FROM rater WHERE name='演示评审'").fetchone()
        if not r:
            r = service.create_rater(conn, "演示评审", "示例")
        print(f"演示评审 id={r['id']} 评审码={r['code']}")
    elif a.cmd == "import":
        for path in a.paths:
            print(path, importer.import_path(conn, path))
    elif a.cmd == "rater":
        r = service.create_rater(conn, a.name, a.expertise)
        print(f"评审 id={r['id']} 名字={r['name']} 评审码={r['code']}")
    elif a.cmd == "batch":
        bid = batching.generate_batch(conn, a.rater, a.line, a.pairs, a.singles, a.sources,
                                      a.control_ratio, a.seed, a.max_len_ratio)
        n = conn.execute("SELECT COUNT(*), SUM(control_type IS NOT NULL) FROM task WHERE batch_id=?", (bid,)).fetchone()
        print(f"批次 {bid}：{n[0]} 题，其中对照题 {n[1]} 道（{n[1] / n[0]:.0%}）")
        import json as _json
        prm = _json.loads(conn.execute("SELECT params_json FROM batch WHERE id=?", (bid,)).fetchone()[0])
        if prm["skipped_len_pairs"]:
            print(f"因长度比超过 {a.max_len_ratio} 跳过 {prm['skipped_len_pairs']} 对")
        if prm["unpaired_sources"]:
            print("注意：这些来源一对都没配上：" + "、".join(prm["unpaired_sources"]))
    elif a.cmd == "serve":
        from .server import serve
        serve(a.db, a.port, a.admin_token)
    elif a.cmd == "simulate":
        for k in range(a.raters):
            rid = simulate.ensure_sim_rater(conn, f"模拟评审{k + 1}")
            for line in ("台词", "口播"):
                try:
                    batching.generate_batch(conn, rid, line, n_pairwise=a.pairs, n_single=4, seed=a.seed * 100 + k)
                except batching.BatchError as e:
                    print(f"模拟评审{k + 1} {line}：{e}")
            n = simulate.simulate(conn, rid, seed=a.seed, left_bias=0.4 if k == 0 else 0.0)
            print(f"模拟评审{k + 1}（id={rid}）答了 {n} 题")
    elif a.cmd == "export":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "judgments.csv").write_text(exporter.to_csv(conn), encoding="utf-8")
        (out / "judgments.jsonl").write_text(exporter.to_jsonl(conn), encoding="utf-8")
        (out / "preference.jsonl").write_text(
            exporter.to_preference_jsonl(conn, include_simulated=a.include_simulated), encoding="utf-8")
        for f in ("judgments.csv", "judgments.jsonl", "preference.jsonl"):
            print(out / f)
    elif a.cmd == "analyze":
        rep = analysis.analyze(conn, n_boot=a.boot, seed=a.seed, include_too_fast=a.include_too_fast,
                               exclude_simulated=a.exclude_simulated, write_back=a.write_back)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        md = analysis.to_markdown(rep)
        (out / "report.md").write_text(md, encoding="utf-8")
        (out / "report.json").write_text(analysis.to_json(rep), encoding="utf-8")
        print(md)
        print(f"已写入 {out / 'report.md'} 和 {out / 'report.json'}")
    elif a.cmd == "status":
        ov = service.overview(conn)
        for it in ov["items"]:
            print(f"{it['line']}：{it['items']} 个条目，{it['variants']} 篇稿件")
        for r in ov["raters"]:
            print(f"评审 {r['id']} {r['name']}：{r['done']}/{r['tasks']} 题，过快 {r['too_fast'] or 0}")


if __name__ == "__main__":
    main()
