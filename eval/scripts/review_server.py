"""盲审：本机审稿页，多人可用。打开就能评，不用评审码，不限人数。

    python eval/scripts/review_server.py --run eval/out/bbtt-full [--port 8770] [--host 127.0.0.1]

- 只读 <run>/blind.json（不透明编号 + 文本）。key.json（编号 → 组合）服务端不读也不发，审完用 reveal.py 揭晓。
- 每个浏览器第一次打开时生成一个匿名 id（存在浏览器里），可以另填称呼。评分按人存到 <run>/ratings/<id>.json。
- 每个人看到的稿子顺序都单独打乱（按匿名 id 和 brief 算），所以不同人的“稿 1”不是同一份。
- 默认只在本机可访问。要让同一局域网里的同事一起评，加 --host 0.0.0.0，再把本机 IP 和端口发给他们。
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PAGE = Path(__file__).with_name("review_page.html")
RATER_ID = re.compile(r"^[a-z0-9]{8,40}$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    run = Path(a.run)
    blind = (run / "blind.json").read_bytes()
    rdir = run / "ratings"
    rdir.mkdir(exist_ok=True)
    lock = threading.Lock()

    def complete_counts() -> dict:
        """每个 brief 有几个人评完（只给人数，不给任何出处）。"""
        data = json.loads(blind)
        need = {b["id"]: {it["vid"] for it in b["items"]} for b in data["briefs"]}
        out = {bid: 0 for bid in need}
        for f in rdir.glob("*.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8")).get("data", {})
            except ValueError:
                continue
            for bid, vids in need.items():
                items = (r.get(bid) or {}).get("items", {})
                if vids and all((items.get(v) or {}).get("ai") and (items.get(v) or {}).get("talk")
                                and (items.get(v) or {}).get("good") for v in vids):
                    out[bid] += 1
        return out

    class H(BaseHTTPRequestHandler):
        def _send(self, code, ctype, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode())

        def _rater(self):
            rid = (parse_qs(urlparse(self.path).query).get("rater") or [""])[0]
            return rid if RATER_ID.match(rid) else None

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
            if path == "/api/data":
                return self._send(200, "application/json; charset=utf-8", blind)
            if path == "/api/progress":
                with lock:
                    return self._json(200, complete_counts())
            if path == "/api/ratings":
                rid = self._rater()
                if not rid:
                    return self._json(400, {"error": "缺匿名 id"})
                f = rdir / f"{rid}.json"
                return self._send(200, "application/json; charset=utf-8",
                                  f.read_bytes() if f.exists() else b'{"name":"","data":{}}')
            self._send(404, "text/plain; charset=utf-8", "没有这个页面".encode())

        def do_POST(self):
            if urlparse(self.path).path != "/api/ratings":
                return self._send(404, "text/plain; charset=utf-8", b"")
            rid = self._rater()
            if not rid:
                return self._json(400, {"error": "缺匿名 id"})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                assert isinstance(body, dict) and isinstance(body.get("data"), dict)
            except Exception:  # noqa: BLE001
                return self._json(400, {"error": "bad json"})
            rec = {"name": str(body.get("name") or "")[:40], "data": body["data"]}
            with lock:
                (rdir / f"{rid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            self._json(200, {"ok": True})

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer((a.host, a.port), H)
    print(f"审稿页：http://{'127.0.0.1' if a.host == '127.0.0.1' else a.host}:{a.port}/   评分保存在 {rdir}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
