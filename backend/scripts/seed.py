"""首次启动演示数据：demo 项目 + 三条代表性 trace（成功 RAG / 工具调用 / 失败限流）。

幂等：demo 项目已存在则跳过。用法：python scripts/seed.py（使用 DATABASE_URL）。
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import secrets

from app.database import Base, SessionLocal, engine
from app.models import Project, User
from app.services.security import ensure_default_admin

DEMO_NAME = "demo"


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_default_admin(db)
        if db.query(Project).filter(Project.name == DEMO_NAME).first():
            print("seed: demo project already exists, skip")
            return
        project = Project(name=DEMO_NAME, api_key=secrets.token_hex(24))
        db.add(project)
        db.commit()
        db.refresh(project)
        key = project.api_key
    finally:
        db.close()

    import urllib.request

    base = os.environ.get("SEED_API_URL", "http://127.0.0.1:8000")

    def post(path, body, headers):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    now = datetime.now(timezone.utc)

    def trace(name, session, status, t0, dur, spans):
        body = {
            "name": name, "session_id": session, "status": status,
            "start_time": t0.isoformat(), "end_time": (t0 + timedelta(milliseconds=dur)).isoformat(),
            "spans": spans,
        }
        if status == "error":
            for s in spans:
                if s.get("parent_span_id") is None and isinstance(s.get("output"), dict) and "error" in s["output"]:
                    body["error"] = s["output"]["error"]
                    break
        post("/api/v1/traces/ingest", body, {"X-API-Key": key})

    sys_prompt = (
        "你是天气预报查询助手，只调用工具 query_weather(name, days, start_date, end_date) 回答用户。\n"
        "- 【用户提到具体日期或区间必须传 start_date/end_date】（yyyy-MM-dd）。\n"
        "- 工具已返回【固定格式】的逐日天气卡片：请【原样输出】，之后补一句简短总结。\n"
        "- 工具失败时如实告知「天气服务暂时不可用」，绝不编造数据。"
    )
    weather_tool_result = (
        "【长沙天气预报】\n11月14日（周六）天气：白天多云，夜间多云；气温：13°C - 20°C；西北风1-3级；湿度：93%\n"
        "11月15日（周日）天气：白天小雨，夜间小雨；气温：12°C - 20°C；北风1-3级；湿度：80%"
    )
    weather_answer = (
        "长沙11月14日-11月15日的天气预报如下：\n**11月14日（周六）**\n- 天气：白天多云，夜间多云\n- 气温：13°C - 20°C\n"
        "- 风向风力：西北风1-3级\n\n**11月15日（周日）**\n- 天气：白天小雨，夜间小雨\n- 气温：12°C - 20°C\n\n"
        "两天昼夜温差较大，早晚需添衣；15日有小雨，建议携带雨具。"
    )
    qa_answer = "您的订单已到达上海转运中心，预计明天下午送达。"

    # 1) RAG 客服问答（chain -> tool -> llm）
    t = now - timedelta(minutes=30)
    r1, tool1, llm1 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    trace("订单查询问答", "demo-thread-1", "ok", t, 1840, [
        {"id": r1, "parent_span_id": None, "name": "agent:客服问答", "span_type": "chain",
         "input": {"question": "我的订单 20261108-003 到哪了？"},
         "output": {"answer": qa_answer},
         "start_time": t.isoformat(), "end_time": (t + timedelta(milliseconds=1840)).isoformat()},
        {"id": tool1, "parent_span_id": r1, "name": "query_order", "span_type": "tool",
         "input": {"order_id": "20261108-003"},
         "output": {"status": "运输中", "location": "上海转运中心", "eta": "明天 15:00"},
         "start_time": (t + timedelta(milliseconds=80)).isoformat(),
         "end_time": (t + timedelta(milliseconds=310)).isoformat()},
        {"id": llm1, "parent_span_id": r1, "name": "gpt-4o-mini", "span_type": "llm", "model": "gpt-4o-mini",
         "input": [{"role": "system", "content": "你是内部客服助手，用简洁中文回答物流问题。"},
                   {"role": "user", "content": "我的订单 20261108-003 到哪了？\n\n[工具结果] 运输中 · 上海转运中心"}],
         "output": {"role": "assistant", "content": qa_answer},
         "prompt_tokens": 186, "completion_tokens": 42, "total_tokens": 228,
         "start_time": (t + timedelta(milliseconds=340)).isoformat(),
         "end_time": (t + timedelta(milliseconds=1780)).isoformat()},
    ])
    print("seed: trace 1/3 (RAG ok)")

    # 2) 天气 Agent 工具调用（llm -> tool_call -> llm 总结）
    t = now - timedelta(minutes=20)
    a1, l1, l2 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    tool_call = {"id": "call_seed_001", "type": "function",
                 "function": {"name": "query_weather",
                              "arguments": json.dumps({"name": "长沙", "start_date": "2026-11-14", "end_date": "2026-11-15"})}}
    trace("天气查询 Agent", "demo-thread-2", "ok", t, 4820, [
        {"id": a1, "parent_span_id": None, "name": "LangGraph", "span_type": "agent",
         "input": "长沙 2026-11-14到2026-11-15 天气", "output": weather_answer,
         "start_time": t.isoformat(), "end_time": (t + timedelta(milliseconds=4820)).isoformat()},
        {"id": l1, "parent_span_id": a1, "name": "ChatOpenAI", "span_type": "llm", "model": "deepseek-flash",
         "input": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": "长沙 2026-11-14到2026-11-15 天气"}],
         "output": {"role": "assistant", "content": "", "tool_calls": [tool_call]},
         "prompt_tokens": 412, "completion_tokens": 38, "total_tokens": 450,
         "start_time": (t + timedelta(milliseconds=60)).isoformat(),
         "end_time": (t + timedelta(milliseconds=1740)).isoformat()},
        {"id": l2, "parent_span_id": a1, "name": "ChatOpenAI", "span_type": "llm", "model": "deepseek-flash",
         "input": [{"role": "system", "content": sys_prompt},
                   {"role": "user", "content": "长沙 2026-11-14到2026-11-15 天气"},
                   {"role": "assistant", "content": "", "tool_calls": [tool_call]},
                   {"role": "tool", "name": "query_weather", "tool_call_id": "call_seed_001", "content": weather_tool_result}],
         "output": {"role": "assistant", "content": weather_answer},
         "prompt_tokens": 1275, "completion_tokens": 310, "total_tokens": 1585,
         "start_time": (t + timedelta(milliseconds=1860)).isoformat(),
         "end_time": (t + timedelta(milliseconds=4760)).isoformat()},
    ])
    print("seed: trace 2/3 (tool calls ok)")

    # 3) 失败链路（限流错误）
    t = now - timedelta(minutes=10)
    r2, l3 = str(uuid.uuid4()), str(uuid.uuid4())
    err = {"type": "rate_limit_error", "message": "Rate limit reached for gpt-4o on tokens per min (TPM)"}
    trace("退款申请处理", "demo-thread-3", "error", t, 9200, [
        {"id": r2, "parent_span_id": None, "name": "agent:退款流程", "span_type": "chain",
         "input": {"question": "商品有质量问题，我要退款"},
         "output": {"error": "tool execution timeout after 9000ms"},
         "start_time": t.isoformat(), "end_time": (t + timedelta(milliseconds=9200)).isoformat()},
        {"id": l3, "parent_span_id": r2, "name": "gpt-4o", "span_type": "llm", "model": "gpt-4o",
         "input": [{"role": "user", "content": "商品有质量问题，我要退款"}],
         "output": {"error": err},
         "prompt_tokens": 3102, "completion_tokens": 0, "total_tokens": 3102,
         "start_time": (t + timedelta(milliseconds=100)).isoformat(),
         "end_time": (t + timedelta(milliseconds=9100)).isoformat()},
    ])
    print("seed: trace 3/3 (error case)")

    print("seed: demo project ready, api_key =", key[:12] + "...")


if __name__ == "__main__":
    seed()
