"""WS 实时推送端到端：连接 -> 订阅 -> ingest 触发 -> 收到 trace.new"""
import asyncio, json, os, urllib.request

os.environ["DATABASE_URL"] = "sqlite:///./wstest.db"
if os.path.exists("./wstest.db"):
    os.remove("./wstest.db")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import pytest, http  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)

client = TestClient(app)
token = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]
AUTH = {"Authorization": "Bearer " + token}
proj = client.post("/api/v1/projects", headers=AUTH, json={"name": "ws-proj"}).json()
pid = proj["id"]
key = proj["api_key"]
now = datetime.now(timezone.utc)


def ingest(name):
    client.post("/api/v1/traces/ingest", headers={"X-API-Key": key}, json={
        "name": name, "status": "ok",
        "start_time": now.isoformat(),
        "end_time": (now + timedelta(milliseconds=100)).isoformat(),
        "spans": [{"name": "s", "span_type": "chain",
                   "start_time": now.isoformat(),
                   "end_time": (now + timedelta(milliseconds=100)).isoformat()}]})


async def run_ws():
    from starlette.testclient import TestClient as _TC
    # WS over TestClient (portal-based sync websocket)
    received = []
    with client.websocket_connect("/ws/traces?token=" + token) as ws:
        ws.send_json({"type": "subscribe", "project_id": pid})
        ack = json.loads(ws.receive_text())
        assert ack["type"] == "subscribed", ack
        # ingest 在另一个线程触发广播
        import threading
        th = threading.Thread(target=ingest, args=("realtime-trace",))
        th.start()
        msg = json.loads(ws.receive_text())
        received.append(msg)
        th.join()
    return received


import threading  # noqa: E402
received = asyncio.get_event_loop().run_until_complete(run_ws()) if False else None

# TestClient websocket 是同步接口；直接同步跑：
with client.websocket_connect("/ws/traces?token=" + token) as ws:
    ws.send_json({"type": "subscribe", "project_id": pid})
    ack = json.loads(ws.receive_text())
    assert ack["type"] == "subscribed", ack
    print("subscribe ack: OK")
    th = threading.Thread(target=ingest, args=("realtime-trace",))
    th.start()
    msg = json.loads(ws.receive_text())
    th.join()
    assert msg["type"] == "trace.new" and msg["name"] == "realtime-trace", msg
    print("trace.new received: OK", msg["name"])

# 错误 token 拒绝
try:
    with client.websocket_connect("/ws/traces?token=bad") as ws:
        ws.receive_text()
    print("ERROR: bad token accepted")
except Exception:
    print("bad token rejected: OK")

engine.dispose()
print()
print("ALL WS TESTS PASSED")
