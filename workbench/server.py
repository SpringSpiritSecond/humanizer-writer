"""本机 HTTP 服务：评审页 /、管理页 /admin，JSON 接口在 /api 下。

- 只监听 127.0.0.1。
- 评审接口用评审码（请求头 X-Rater-Code）；管理接口用管理口令（请求头 X-Admin-Token），
  口令在启动时打印，也可以用环境变量 WB_ADMIN_TOKEN 固定下来。
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import analysis, batching, exporter, importer, service
from .db import connect
from .service import ApiError

STATIC = Path(__file__).resolve().parent / "static"


class App:
    def __init__(self, conn: sqlite3.Connection, admin_token: str):
        self.conn = conn
        self.admin_token = admin_token
        self.lock = threading.Lock()

    # 返回 (status, content_type, body_bytes, extra_headers)
    def handle(self, method: str, path: str, query: dict, headers: dict, body: bytes):
        if method == "GET" and path in ("/", "/review"):
            return self._static("review.html")
        if method == "GET" and path == "/admin":
            return self._static("admin.html")
        if not path.startswith("/api/"):
            return 404, "text/plain; charset=utf-8", "没有这个页面".encode(), {}
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._json(400, {"error": "请求不是合法 JSON"})
        try:
            with self.lock:
                if path.startswith("/api/rater/"):
                    return self._rater(method, path, headers, data)
                if path.startswith("/api/admin/"):
                    if not secrets.compare_digest(headers.get("x-admin-token", ""), self.admin_token):
                        raise ApiError(403, "需要管理口令")
                    return self._admin(method, path, query, data)
                if path == "/api/meta":
                    return self._json(200, {"tags": service.TAGS, "conf_labels": service.CONF_LABELS})
            raise ApiError(404, "没有这个接口")
        except ApiError as e:
            return self._json(e.status, {"error": e.msg})
        except (importer.ImportErrorWB, batching.BatchError) as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._json(500, {"error": f"服务端出错：{e}"})

    def _static(self, name):
        return 200, "text/html; charset=utf-8", (STATIC / name).read_bytes(), {"Cache-Control": "no-store"}

    def _json(self, status, obj):
        return status, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode(), {}

    def _file(self, text, ctype, name):
        from urllib.parse import quote
        return 200, ctype, text.encode("utf-8"), {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}

    # ----- 评审端 -----
    def _rater(self, method, path, headers, data):
        r = service.rater_by_code(self.conn, headers.get("x-rater-code", ""))
        parts = path.strip("/").split("/")          # api rater ...
        if method == "GET" and parts[2:] == ["me"]:
            return self._json(200, {"name": r["name"]})
        if method == "GET" and parts[2:] == ["queue"]:
            return self._json(200, service.rater_queue(self.conn, r["id"]))
        if len(parts) == 4 and parts[2] == "task" and method == "GET":
            return self._json(200, service.rater_task(self.conn, r["id"], parts[3]))
        if len(parts) == 5 and parts[2] == "task" and parts[4] == "judgment" and method == "POST":
            return self._json(200, service.submit_judgment(self.conn, r["id"], parts[3], data))
        raise ApiError(404, "没有这个接口")

    # ----- 管理端 -----
    def _admin(self, method, path, query, data):
        sub = path[len("/api/admin/"):]
        c = self.conn
        if method == "GET" and sub == "overview":
            return self._json(200, service.overview(c))
        if method == "POST" and sub == "import":
            fmt = data.get("format", "json")
            if fmt == "csv":
                res = importer.import_csv_text(c, data.get("content", ""), data.get("filename", "csv"))
            else:
                content = data.get("content")
                payload = json.loads(content) if isinstance(content, str) else content
                res = importer.import_json(c, payload, data.get("filename", "json"))
            return self._json(200, res)
        if method == "POST" and sub == "raters":
            if not data.get("name"):
                raise ApiError(400, "评审要有名字")
            return self._json(200, service.create_rater(c, data["name"], data.get("expertise", "")))
        if method == "POST" and sub == "batches":
            bid = batching.generate_batch(
                c, int(data["rater_id"]), data["line"], n_pairwise=int(data.get("n_pairwise", 24)),
                n_single=int(data.get("n_single", 4)), sources=data.get("sources") or None,
                control_ratio=float(data.get("control_ratio", batching.CONTROL_TARGET)),
                seed=int(data["seed"]) if data.get("seed") not in (None, "") else None,
                max_len_ratio=float(data.get("max_len_ratio", 1.5)))
            return self._json(200, {"batch_id": bid})
        if method == "GET" and sub.startswith("export/"):
            kind = sub.split("/", 1)[1]
            if kind == "csv":
                return self._file(exporter.to_csv(c), "text/csv; charset=utf-8", "judgments.csv")
            if kind == "jsonl":
                return self._file(exporter.to_jsonl(c), "application/x-ndjson; charset=utf-8", "judgments.jsonl")
            if kind == "preference":
                sim = query.get("include_simulated", ["0"])[0] == "1"
                return self._file(exporter.to_preference_jsonl(c, include_simulated=sim),
                                  "application/x-ndjson; charset=utf-8", "preference.jsonl")
        if method == "GET" and sub == "analysis":
            n_boot = int(query.get("n_boot", ["500"])[0])
            rep = analysis.analyze(c, n_boot=n_boot)
            return self._json(200, {"markdown": analysis.to_markdown(rep), "report": json.loads(analysis.to_json(rep))})
        raise ApiError(404, "没有这个接口")


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _go(self, method):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            status, ctype, out, extra = app.handle(method, u.path, parse_qs(u.query), hdrs, body)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(out)))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(db=None, port=8765, admin_token=None):
    token = admin_token or os.environ.get("WB_ADMIN_TOKEN") or secrets.token_urlsafe(12)
    app = App(connect(db), token)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"盲审工作台已启动（只在本机）：")
    print(f"  评审页  http://127.0.0.1:{port}/")
    print(f"  管理页  http://127.0.0.1:{port}/admin   管理口令：{token}")
    print("Ctrl+C 退出")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
