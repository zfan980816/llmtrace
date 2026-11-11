# -*- coding: utf-8 -*-
"""LangSmith 兼容端点端到端测试：JSON batch + multipart + 可读命名 + token/成本聚合 + 错误状态。

运行：python langsmith_compat_test.py  （DATABASE_URL 自动指向本测试 sqlite）
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./langsmith_compat_test.db"
if os.path.exists("./langsmith_compat_test.db"):
    os.remove("./langsmith_compat_test.db")

import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Project
from app.services.security import ensure_default_admin

Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    ensure_default_admin(db)
    p = Project(name="ls-compat-test", api_key="lscompatkey00000000000000000000000000")
    db.add(p)
    db.commit()

client = TestClient(app)
BASE = "http://testserver"
KEY = {"X-API-Key": p.api_key}
NOW = datetime.now(timezone.utc)
iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
dstamp = lambda dt: dt.strftime("%Y%m%dT%H%M%S%fZ")

# ---- 0) /info 探测 ----
r = client.get(f"{BASE}/info")
assert r.status_code == 200 and r.json()["batch_ingest_config"]["size_limit"] > 0
print("info probe: OK")

# ---- 1) JSON batch：根 chain + llm 子 span，patch 回填 ----
rid, lid = uuid.uuid4(), uuid.uuid4()
t_iso = iso(NOW)
root_do = f"{dstamp(NOW)}{rid}"
child_do = f"{root_do}.{dstamp(NOW)}{lid}"
r = client.post(f"{BASE}/runs/batch", headers=KEY, json={"post": [
    {"id": str(rid), "trace_id": str(rid), "dotted_order": root_do, "name": "LangGraph",
     "run_type": "chain", "inputs": {"user_message": "帮我规划上海3天行程"}, "start_time": t_iso,
     "session_name": "travel_plan", "extra": {"metadata": {"thread_id": "job-abc"}}},
    {"id": str(lid), "trace_id": str(rid), "parent_run_id": str(rid), "dotted_order": child_do,
     "name": "ChatOpenAI", "run_type": "llm",
     "inputs": {"messages": [[{"lc": 1, "type": "constructor",
                               "id": ["langchain", "schema", "messages", "HumanMessage"],
                               "kwargs": {"content": "上海有什么好玩的", "type": "human"}}]]},
     "start_time": t_iso, "extra": {"metadata": {"ls_model_name": "deepseek-chat"}},
     "session_name": "travel_plan"},
]})
assert r.status_code == 202, r.text
r = client.post(f"{BASE}/runs/batch", headers=KEY, json={"patch": [
    {"id": str(lid), "trace_id": str(rid), "dotted_order": child_do, "name": "ChatOpenAI",
     "run_type": "llm",
     "outputs": {"generations": [[{"text": "外滩、豫园…", "message": {"lc": 1, "type": "constructor",
                   "id": ["langchain", "schema", "messages", "AIMessage"],
                   "kwargs": {"content": "外滩、豫园…", "type": "ai"}}}]],
                 "llm_output": {"token_usage": {"prompt_tokens": 20, "completion_tokens": 10,
                                                "total_tokens": 30}}},
     "end_time": iso(NOW + timedelta(seconds=2)),
     "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    {"id": str(rid), "trace_id": str(rid), "dotted_order": root_do, "name": "LangGraph",
     "run_type": "chain", "outputs": {"itinerary": "D1 外滩…"},
     "end_time": iso(NOW + timedelta(seconds=3))},
]})
assert r.status_code == 202, r.text

from app.models import Span, Trace
with SessionLocal() as db:
    t = db.get(Trace, rid)
    assert t is not None, "trace missing"
    assert t.name == "帮我规划上海3天行程", f"readable name wrong: {t.name}"
    assert t.status == "ok" and t.session_id == "job-abc"
    assert (t.prompt_tokens, t.completion_tokens, t.total_tokens) == (20, 10, 30)
    # deepseek-chat: 20/1e6*0.27 + 10/1e6*1.10 = 0.0000054+0.000011
    assert t.cost > 0, f"cost not computed: {t.cost}"
    spans = db.query(Span).filter(Span.trace_id == rid).all()
    assert len(spans) == 2
    llm = next(s for s in spans if s.span_type == "llm")
    assert llm.status == "ok" and llm.model == "deepseek-chat"
    assert llm.prompt_tokens == 20 and llm.cost > 0
    assert json.loads(json.dumps(llm.output))["messages"][0]["role"] == "ai"
    assert json.loads(json.dumps(llm.input))["messages"][0]["role"] == "human"
print("json batch + naming + cost: OK")

# ---- 2) 错误 run：span 与 trace 都记 error ----
rid2 = uuid.uuid4()
r = client.post(f"{BASE}/runs/batch", headers=KEY, json={"post": [
    {"id": str(rid2), "trace_id": str(rid2), "dotted_order": f"{dstamp(NOW)}{rid2}",
     "name": "ChatOpenAI", "run_type": "llm", "inputs": {"messages": [[{"role": "user", "content": "hi"}]]},
     "start_time": t_iso, "extra": {"metadata": {"ls_model_name": "qwen-plus"}}}]})
assert r.status_code == 202
r = client.post(f"{BASE}/runs/batch", headers=KEY, json={"patch": [
    {"id": str(rid2), "trace_id": str(rid2), "name": "ChatOpenAI", "run_type": "llm",
     "error": "Error code: 403 - quota exhausted", "end_time": iso(NOW + timedelta(seconds=1))}]})
assert r.status_code == 202
with SessionLocal() as db:
    t2 = db.get(Trace, rid2)
    assert t2.status == "error" and "403" in (t2.error or "")
    s2 = db.query(Span).filter(Span.trace_id == rid2).first()
    assert s2.status == "error" and "403" in s2.error
print("error status: OK")

# ---- 3) multipart：现代客户端默认路径 ----
rid3, lid3 = uuid.uuid4(), uuid.uuid4()
main = {"id": str(rid3), "trace_id": str(rid3), "dotted_order": f"{dstamp(NOW)}{rid3}",
        "name": "plan:mp", "run_type": "chain",
        "start_time": t_iso, "session_name": "travel_plan"}
frag = {"user_message": "multipart 冒烟"}
llm_main = {"id": str(lid3), "trace_id": str(rid3), "parent_run_id": str(rid3),
            "dotted_order": f"{dstamp(NOW)}{rid3}.{dstamp(NOW)}{lid3}",
            "name": "ChatOpenAI", "run_type": "llm", "start_time": t_iso,
            "extra": {"metadata": {"ls_model_name": "qwen-plus"}}}
r = client.post(f"{BASE}/runs/multipart", headers=KEY, files={
    f"post.{rid3}": (None, json.dumps(main).encode(), "application/json"),
    f"post.{rid3}.inputs": (None, json.dumps(frag).encode(), "application/json"),
    f"post.{lid3}": (None, json.dumps(llm_main).encode(), "application/json"),
})
assert r.status_code == 202, r.text
with SessionLocal() as db:
    t3 = db.get(Trace, rid3)
    assert t3 is not None and t3.name == "plan:mp"
    assert t3.input == {"user_message": "multipart 冒烟"}, f"fragment lost: {t3.input}"
    assert db.query(Span).filter(Span.trace_id == rid3).count() == 2
print("multipart ingest: OK")

# ---- 4) 鉴权 ----
r = client.post(f"{BASE}/runs/batch", json={"post": []})
assert r.status_code in (401, 403, 422), f"auth not enforced: {r.status_code}"
print("auth enforced: OK")

print("\nALL LANGSMITH COMPAT TESTS PASSED")
