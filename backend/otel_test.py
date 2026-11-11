"""OTLP/HTTP(JSON) 接入测试：GenAI 语义约定 → 内部 trace/span 结构。"""
import os
os.environ["DATABASE_URL"] = "sqlite:///./otel_test.db"
if os.path.exists("./otel_test.db"):
    os.remove("./otel_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)
admin = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()
AUTH = {"Authorization": "Bearer " + admin["token"]}
proj = client.post("/api/v1/projects", headers=AUTH, json={"name": "otel-proj"}).json()
KEY = {"X-API-Key": proj["api_key"]}

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ROOT = "00f067aa0ba902b7"
SPAN_LLM = "00f067aa0ba902b8"

doc = {
    "resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "weather-agent"}},
            {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
        ]},
        "scopeSpans": [{"spans": [
            {
                "traceId": TRACE_ID, "spanId": SPAN_ROOT,
                "name": "weather-agent.run",
                "kind": 1,
                "startTimeUnixNano": 1731216000000000000,
                "endTimeUnixNano": 1731216001482000000,
                "attributes": [
                    {"key": "openinference.span.kind", "value": {"stringValue": "AGENT"}},
                    {"key": "input.value", "value": {"stringValue": "长沙天气"}},
                ],
                "status": {"code": 1},
            },
            {
                "traceId": TRACE_ID, "spanId": SPAN_LLM, "parentSpanId": SPAN_ROOT,
                "name": "chat.completions",
                "kind": 3,
                "startTimeUnixNano": 1731216000100000000,
                "endTimeUnixNano": 1731216001400000000,
                "attributes": [
                    {"key": "openinference.span.kind", "value": {"stringValue": "LLM"}},
                    {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o-mini"}},
                    {"key": "gen_ai.prompt.1.content", "value": {"stringValue": "长沙 2026-11-14 天气"}},
                    {"key": "gen_ai.prompt.1.role", "value": {"stringValue": "user"}},
                    {"key": "gen_ai.completion.1.content", "value": {"stringValue": "晴天 15 度"}},
                    {"key": "gen_ai.completion.1.role", "value": {"stringValue": "assistant"}},
                    {"key": "gen_ai.usage.prompt_tokens", "value": {"intValue": 120}},
                    {"key": "gen_ai.usage.completion_tokens", "value": {"intValue": 30}},
                ],
                "status": {"code": 1},
            },
        ]}],
    }],
}

# 1. ingest
r = client.post("/api/v1/otel/v1/traces", headers=KEY, json=doc)
assert r.status_code == 201, r.text
assert r.json()["count"] == 1
tid = r.json()["ids"][0]
print("otel ingest: OK", tid[:8])

# 2. 内部结构断言（走普通 trace 详情接口）
r = client.get("/api/v1/traces/" + tid, headers=AUTH)
t = r.json()
assert t["name"] == "weather-agent", t["name"]
assert t["status"] == "ok"
assert t["total_tokens"] == 150
assert len(t["spans"]) == 2
spans = {s["name"]: s for s in t["spans"]}
root = spans["weather-agent.run"]
llm = spans["chat.completions"]
assert root["span_type"] == "agent" and root["input"] == {"text": "长沙天气"}
assert root["latency_ms"] == 1482
assert llm["span_type"] == "llm" and llm["model"] == "gpt-4o-mini"
assert llm["parent_span_id"] == root["id"]
assert llm["prompt_tokens"] == 120 and llm["completion_tokens"] == 30
assert llm["cost"] > 0
msgs = llm["input"]
assert isinstance(msgs, list) and msgs[0]["role"] == "user" and "长沙" in msgs[0]["content"]
assert llm["output"]["role"] == "assistant" and "晴天" in llm["output"]["content"]
assert (llm.get("meta") or {}).get("otel.resource") == "openai"
print("otel mapping: OK (agent/llm, tokens, cost, messages)")

# 3. 错误 span
doc["resourceSpans"][0]["scopeSpans"][0]["spans"] = [{
    "traceId": "5bf92f3577b34da6a3ce929d0e0e4737", "spanId": "10f067aa0ba902b7",
    "name": "failing-llm", "kind": 3,
    "startTimeUnixNano": 1731216100000000000, "endTimeUnixNano": 1731216101000000000,
    "attributes": [{"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}}],
    "status": {"code": 2, "message": "rate_limit_error: TPM exceeded"},
}]
r = client.post("/api/v1/otel/v1/traces", headers=KEY, json=doc)
assert r.status_code == 201
tid2 = r.json()["ids"][0]
t2 = client.get("/api/v1/traces/" + tid2, headers=AUTH).json()
assert t2["status"] == "error" and "rate_limit" in t2["error"]
assert t2["spans"][0]["status"] == "error"
assert t2["output"] == {"error": "rate_limit_error: TPM exceeded"}
print("otel error mapping: OK")

# 4. 错误 key
r = client.post("/api/v1/otel/v1/traces", json=doc, headers={"X-API-Key": "bad"})
assert r.status_code == 401
print("bad key rejected: OK")

# 5. 空 payload
r = client.post("/api/v1/otel/v1/traces", headers=KEY, json={})
assert r.status_code == 422
print("empty payload rejected: OK")

engine.dispose()
print()
print("ALL OTEL TESTS PASSED")
