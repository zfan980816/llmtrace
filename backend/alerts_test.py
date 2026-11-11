"""Alert rules smoke test (SQLite). Run: python alerts_test.py"""
import os
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///./alerts_test.db"

if os.path.exists("./alerts_test.db"):
    os.remove("./alerts_test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.security import ensure_default_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
with SessionLocal() as _db:
    ensure_default_admin(_db)
client = TestClient(app)

_r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
AUTH = {"Authorization": "Bearer " + _r.json()["token"]}

r = client.post("/api/v1/projects", json={"name": "alerts-test"}, headers=AUTH)
project = r.json()
headers = AUTH
ING = {"X-API-Key": project["api_key"]}
PID = project["id"]

# 1. create rule: error_rate > 0.2 within 60 min
r = client.post("/api/v1/alerts/rules", headers=headers, json={
    "project_id": PID,
    "name": "错误率过高",
    "metric_type": "error_rate",
    "threshold": 0.2,
    "window_minutes": 60,
})
assert r.status_code == 201, r.text
rule = r.json()
print("rule created:", rule["id"])

# 2. invalid metric_type rejected
r = client.post("/api/v1/alerts/rules", headers=headers, json={
    "project_id": PID, "name": "bad", "metric_type": "nope", "threshold": 1, "window_minutes": 5,
})
assert r.status_code == 422
print("invalid metric rejected: OK")

# 3. ingest 2 traces (1 error) -> error_rate = 0.5 > 0.2
now = datetime.now(timezone.utc)
for i, status in enumerate(["ok", "error"]):
    payload = {
        "name": "t" + str(i),
        "status": status,
        "error": "boom" if status == "error" else None,
        "start_time": now.isoformat(),
        "end_time": now.isoformat(),
        "spans": [{
            "name": "t" + str(i), "status": status,
            "start_time": now.isoformat(), "end_time": now.isoformat(),
        }],
    }
    r = client.post("/api/v1/traces/ingest", json=payload, headers=ING)
    assert r.status_code == 201, r.text

# 4. evaluate -> should trigger exactly 1 alert
r = client.post("/api/v1/alerts/evaluate", headers=headers)
assert r.status_code == 200, r.text
events = r.json()
assert len(events) == 1, events
print("alert triggered:", events[0]["message"])

# 5. evaluate again -> cooldown blocks duplicate
r = client.post("/api/v1/alerts/evaluate", headers=headers)
assert r.status_code == 200 and r.json() == [], r.text
print("cooldown respected: OK")

# 6. events list
r = client.get("/api/v1/alerts/events", headers=headers)
assert r.status_code == 200 and len(r.json()) == 1
print("events list: OK")

# 7. toggle + delete rule
r = client.patch("/api/v1/alerts/rules/" + rule["id"], headers=headers, json={"enabled": False})
assert r.status_code == 200 and r.json()["enabled"] is False
r = client.delete("/api/v1/alerts/rules/" + rule["id"], headers=headers)
assert r.status_code == 204
print("toggle + delete: OK")

engine.dispose()
print("")
print("ALL ALERT TESTS PASSED")


