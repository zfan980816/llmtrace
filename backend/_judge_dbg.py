import json, os
os.environ["DATABASE_URL"] = "sqlite:///./jdbg.db"
if os.path.exists("./jdbg.db"): os.remove("./jdbg.db")
from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine
from app.main import app
from app.services.security import ensure_default_admin
Base.metadata.create_all(bind=engine)
with SessionLocal() as d: ensure_default_admin(d)
c = TestClient(app)
a = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()["token"]
A = {"Authorization": "Bearer " + a}
p = c.post("/api/v1/projects", headers=A, json={"name": "jp"}).json()
DS = c.post("/api/v1/evals/datasets", headers=A, json={"project_id": p["id"], "name": "j"}).json()["id"]
c.post(f"/api/v1/evals/datasets/{DS}/items", headers=A,
       json={"inputs": {"q": "推荐一本机器学习书"}, "expected_output": None})

calls = []
class FakeResp:
    status_code = 200
    def json(self):
        calls.append(json.loads(json.dumps(self._body["messages"])))
        if calls[-1][0]["role"] == "system" and "evaluator" in calls[-1][0]["content"]:
            return {"choices": [{"message": {"content": '{"score": 0.9, "reason": "good rec"}'}}]}
        return {"choices": [{"message": {"content": "《机器学习》周志华"}}], "usage": {}}
class FC:
    def __init__(self, **kw): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def post(self, url, **kw):
        f = FakeResp(); f._body = kw["json"]; return f
import httpx
httpx.Client = FC

r = c.post(f"/api/v1/evals/datasets/{DS}/run", headers=A,
           json={"model": "gpt-4o-mini", "api_key": "k", "judge": True})
print("run:", r.json())
run_id = r.json()["id"]
res = c.get(f"/api/v1/evals/runs/{run_id}", headers=A).json()["results"][0]
print("score:", res["score"], "passed:", res["passed"], "error:", res["error"])
print("output:", json.dumps(res["output"], ensure_ascii=False)[:200])
print("calls:", len(calls), [calls[i][0]["role"] for i in range(len(calls))])
