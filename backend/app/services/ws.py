"""WebSocket 连接管理：ingest 后广播新 trace 事件。"""
import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

import jwt as pyjwt
import uuid

from ..config import settings
from ..database import SessionLocal
from ..models import Project, User

router = APIRouter()


class Hub:
    def __init__(self):
        self._clients: dict[int, set[WebSocket]] = {}  # project_id -> sockets
        self._lock = asyncio.Lock()
        self.main_loop: asyncio.AbstractEventLoop | None = None  # WS 所在事件循环

    async def connect(self, project_id: int, ws: WebSocket):
        async with self._lock:
            self._clients.setdefault(project_id, set()).add(ws)
        if self.main_loop is None:
            self.main_loop = asyncio.get_running_loop()

    async def disconnect(self, project_id: int, ws: WebSocket):
        async with self._lock:
            self._clients.get(project_id, set()).discard(ws)

    async def broadcast(self, project_id: int, payload: dict):
        data = json.dumps(payload)
        dead = []
        async with self._lock:
            socks = list(self._clients.get(project_id, set()))
        for ws in socks:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(project_id, ws)


hub = Hub()


def notify_trace(project_id, trace_id: str, name: str, status: str):
    """在 ingest（同步上下文/线程池）后调用：线程安全地调度到 WS 事件循环广播。"""
    payload = {"type": "trace.new", "trace_id": str(trace_id), "name": name, "status": status}
    loop = hub.main_loop
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(hub.broadcast(project_id, payload)))
    else:
        try:
            loop2 = asyncio.get_running_loop()
            loop2.create_task(hub.broadcast(project_id, payload))
        except RuntimeError:
            pass  # 无 WS 连接过，忽略


@router.websocket("/ws/traces")
async def ws_traces(ws: WebSocket, token: str = ""):
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = uuid.UUID(payload["sub"])
    except pyjwt.PyJWTError:
        await ws.close(code=4401)
        return
    await ws.accept()
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if u is None or not u.is_active:
            await ws.close(code=4401)
            return
        # 接收订阅消息 {"type":"subscribe","project_id":"..."}
        project_id = None
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if msg.get("type") == "subscribe":
                try:
                    pid = uuid.UUID(msg.get("project_id"))
                except (TypeError, ValueError):
                    pid = None
                proj = db.get(Project, pid) if pid else None
                if proj is None:
                    await ws.send_text(json.dumps({"type": "error", "detail": "project 不存在"}))
                    continue
                if project_id is not None:
                    await hub.disconnect(project_id, ws)
                project_id = proj.id
                await hub.connect(project_id, ws)
                await ws.send_text(json.dumps({"type": "subscribed", "project_id": str(project_id)}))
            elif msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        if project_id is not None:
            await hub.disconnect(project_id, ws)
        db.close()
