import json
from pathlib import Path

import pytest

from workbench import importer, service
from workbench.db import connect
from workbench.server import App

SEED = Path(__file__).resolve().parents[1] / "workbench" / "seed"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.sqlite3")
    importer.import_path(c, SEED / "示例_briefs与稿件.json")
    importer.import_path(c, SEED / "示例_候选稿.csv")
    yield c
    c.close()


@pytest.fixture
def rater(conn):
    return service.create_rater(conn, "测试评审")


@pytest.fixture
def app(conn):
    return App(conn, "admintok")


def call(app, method, path, *, code=None, admin=None, body=None, query=None):
    headers = {}
    if code:
        headers["x-rater-code"] = code
    if admin:
        headers["x-admin-token"] = admin
    status, ctype, out, _ = app.handle(method, path, query or {}, headers,
                                       json.dumps(body, ensure_ascii=False).encode() if body is not None else b"")
    return status, (json.loads(out) if ctype.startswith("application/json") and out else out.decode("utf-8"))
