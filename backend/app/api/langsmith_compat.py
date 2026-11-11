"""LangSmith-compatible ingestion endpoints.

The langsmith Python client (bundled with langchain-core) posts runs to
POST /runs/batch (JSON) or POST /runs/multipart (form fragments); single
POST /runs and PATCH /runs/{id} are supported too. GET /info serves the
batch config the client probes on startup.

Mapping: Trace.id = langsmith trace_id, Span.id = run id, so every write is
an idempotent upsert by primary key. Child runs resolve their parent span by
pk, and the root run patch fills in trace summary fields (status, latency,
token/cost totals).
"""

import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..api.deps import get_project
from ..database import get_db
from ..models import Project, Span, Trace
from ..services.cost import estimate_cost

router = APIRouter(tags=["langsmith-compat"])

# langsmith run_type -> LLMTrace span_type
_SPAN_TYPES = {"llm": "llm", "chat_model": "llm", "tool": "tool",
               "retriever": "retrieval", "embedding": "embedding",
               "agent": "agent", "chain": "chain"}


def _parse_dt(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ms(start, end):
    if not start or not end:
        return 0
    return max(0, int((end - start).total_seconds() * 1000))


def _extra_meta(run):
    extra = run.get("extra") or {}
    md = extra.get("metadata") or {}
    return md if isinstance(md, dict) else {}


def _unwrap_msg(m):
    """langchain 序列化消息 -> {role, content, ...}，兼容 lc constructor 和纯 dict。"""
    if not isinstance(m, dict):
        return {"role": "user", "content": str(m)}
    kw = m.get("kwargs") if isinstance(m.get("kwargs"), dict) else None
    if kw is not None and m.get("type") == "constructor":
        out = {"role": kw.get("type") or "user", "content": kw.get("content")}
        ak = kw.get("additional_kwargs") or {}
        if isinstance(ak, dict) and ak.get("tool_calls"):
            out["tool_calls"] = ak["tool_calls"]
        if kw.get("tool_call_id"):
            out["tool_call_id"] = kw["tool_call_id"]
        return out
    out = {k: m[k] for k in ("role", "content", "tool_calls", "tool_call_id")
           if m.get(k) is not None}
    out["role"] = m.get("role") or m.get("type") or "user"
    return out


def _extract_model(run):
    model = _extra_meta(run).get("ls_model_name")
    if not model:
        ser = run.get("serialized") or {}
        model = (ser.get("kwargs") or {}).get("model") if isinstance(ser, dict) else None
    return model


def _extract_tokens(run):
    p = int(run.get("prompt_tokens") or 0)
    c = int(run.get("completion_tokens") or 0)
    if not (p or c):
        out = run.get("outputs") or {}
        tu = out.get("token_usage") if isinstance(out, dict) else None
        if not tu and isinstance(out, dict):
            llo = out.get("llm_output") or {}
            tu = llo.get("token_usage") if isinstance(llo, dict) else None
        if isinstance(tu, dict):
            p = int(tu.get("prompt_tokens") or tu.get("input_tokens") or 0)
            c = int(tu.get("completion_tokens") or tu.get("output_tokens") or 0)
    return p, c, p + c


def _norm_llm_inputs(run, value):
    """LLM run 的 inputs 形如 {"messages": [[msg, ...]]}，摊平并解包消息。"""
    if run.get("run_type") not in ("llm", "chat_model"):
        return value
    if isinstance(value, dict):
        msgs = value.get("messages")
        if isinstance(msgs, list) and msgs:
            flat = []
            for batch in (msgs if isinstance(msgs[0], list) else [msgs]):
                flat.extend(_unwrap_msg(m) for m in (batch or []))
            value = {**value, "messages": flat}
    return value


def _norm_llm_outputs(run, value):
    """LLM run 的 outputs 转成 {"messages": [...]}，前端直接渲染气泡。"""
    if run.get("run_type") not in ("llm", "chat_model") or not isinstance(value, dict):
        return value
    gens = value.get("generations")
    if not isinstance(gens, list):
        return value
    msgs = []
    for batch in gens:
        for gen in (batch or []):
            if not isinstance(gen, dict):
                continue
            msg = gen.get("message") if isinstance(gen.get("message"), dict) else {}
            kw = msg.get("kwargs") if isinstance(msg.get("kwargs"), dict) else None
            if kw is not None and msg.get("type") == "constructor":
                unwrapped = _unwrap_msg(msg)
            else:
                content = msg.get("content")
                text = gen.get("text") or (content if isinstance(content, str) else content)
                unwrapped = {"role": msg.get("type") or "ai", "content": text}
                tc = (msg.get("additional_kwargs") or {}).get("tool_calls")
                if tc:
                    unwrapped["tool_calls"] = tc
                um = msg.get("usage_metadata")
                if um:
                    unwrapped["usage_metadata"] = um
            unwrapped.setdefault("role", "ai")
            msgs.append(unwrapped)
    return {"messages": msgs} if msgs else value


def _short_label(text, cap=20):
    """提取领域名做展示：冒号形态取主语（景点地址：上海 -> 景点地址），
    无冒号取首个逗号短句，都不破坏词语。"""
    s = re.sub(r"\s+", " ", str(text)).strip()
    if not s:
        return ""
    seg = re.split(r"[。！？!?；;\n]", s)[0].strip() or s
    colons = [i for i in (seg.find("："), seg.find(":")) if i >= 0]
    if colons:
        key = seg[:min(colons)].strip()
        if 2 <= len(key) <= 12:
            return key
    first = re.split(r"[，,、]", seg)[0].strip()
    if len(first) >= 4:
        seg = first
    if len(seg) > cap:
        seg = seg[:cap] + "…"
    return seg


def _readable_name(run):
    """根 trace 的展示名。框架内部名（LangGraph/ChatOpenAI）没有业务含义，
    从 inputs 里挖用户消息；llm 类型的根 run 一律尝试提取。"""
    name = str(run.get("name") or "")
    is_llm_root = str(run.get("run_type") or "") in ("llm", "chat_model")
    if name.lower() not in ("langgraph", "langchain", "chain", "agent", "agentexecutor",
                            "runnablesequence", "runnable", "router", "executor") and not is_llm_root:
        return name
    ins = run.get("inputs") if isinstance(run.get("inputs"), dict) else {}
    for k in ("user_message", "query", "question", "input", "prompt", "task", "message"):
        v = ins.get(k)
        if isinstance(v, str) and v.strip():
            return _short_label(v)
    msgs = ins.get("messages")
    if isinstance(msgs, list) and msgs:
        flat = msgs if isinstance(msgs[0], list) else [msgs]
        for batch in flat:
            for m in (batch or []):
                uw = _unwrap_msg(m)
                if uw.get("role") in ("human", "user") and uw.get("content"):
                    return _short_label(str(uw["content"]))
    for v in ins.values():
        if isinstance(v, str) and v.strip():
            return _short_label(v)
    return name or "trace"


def _span_meta(run):
    tags = run.get("tags") or []
    md = _extra_meta(run)
    meta = {}
    if tags:
        meta["tags"] = tags
    if md:
        meta["ls_metadata"] = md
    return meta or None


def _agg_trace_totals(db, trace_id):
    # autoflush=False，先落 pending 的 span 变更再聚合
    db.flush()
    row = db.query(
        func.coalesce(func.sum(Span.prompt_tokens), 0),
        func.coalesce(func.sum(Span.completion_tokens), 0),
        func.coalesce(func.sum(Span.total_tokens), 0),
    ).filter(Span.trace_id == trace_id).one()
    cost = db.query(func.coalesce(func.sum(Span.cost), 0.0)).filter(
        Span.trace_id == trace_id, Span.span_type == "llm").scalar()
    t = db.get(Trace, trace_id)
    if t:
        t.prompt_tokens, t.completion_tokens, t.total_tokens = int(row[0]), int(row[1]), int(row[2])
        t.cost = round(float(cost or 0.0), 6)


def _apply_run(db, project: Project, run: dict, is_create: bool):
    try:
        rid = uuid.UUID(str(run["id"]))
        tid = uuid.UUID(str(run.get("trace_id") or run["id"]))
    except (KeyError, ValueError):
        return
    start = _parse_dt(run.get("start_time")) or datetime.now(timezone.utc)
    end = _parse_dt(run.get("end_time")) or start
    status = "error" if run.get("error") else "ok"
    raw_type = str(run.get("run_type") or "chain")
    span_type = _SPAN_TYPES.get(raw_type, "chain")
    parent_id = uuid.UUID(str(run["parent_run_id"])) if run.get("parent_run_id") else None
    is_root = parent_id is None

    # langgraph: 按名字细分节点类型（graph=agent, model=llm, tools=tool）
    lname = (run.get("name") or "").lower()
    if span_type == "chain":
        if lname == "langgraph":
            span_type = "agent"
        elif lname == "model":
            span_type = "llm"
        elif lname == "tools":
            span_type = "tool"
        elif parent_id is not None:
            parent = db.get(Span, parent_id)
            if parent is not None and (parent.name or "").lower() == "tools":
                span_type = "tool"

    trace = db.get(Trace, tid)
    if trace is None:
        md = _extra_meta(run)
        trace = Trace(
            id=tid, project_id=project.id,
            name=_short_label(run.get("name"))[:200] or "trace",
            session_id=(md.get("thread_id") and str(md["thread_id"])) or None,
            status="ok", error=None,
            input=_norm_llm_inputs(run, run.get("inputs")),
            output=None,
            meta={"langsmith_project": run.get("session_name") or None,
                  "ls_trace_id": str(tid)},
            start_time=start, end_time=end, latency_ms=0,
        )
        db.add(trace)
        db.flush()

    span = db.get(Span, rid)
    if span is None:
        if not is_create:
            return
        span = Span(
            id=rid, trace_id=tid, parent_span_id=parent_id,
            name=str(run.get("name") or "run"),
            span_type=span_type, model=_extract_model(run),
            status="ok", error=None,
            input=_norm_llm_inputs(run, run.get("inputs")),
            output=None, meta=_span_meta(run),
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            start_time=start, end_time=end, latency_ms=0,
        )
        db.add(span)
        db.flush()
    else:
        span.trace_id = tid if not span.trace_id else span.trace_id
        span.parent_span_id = parent_id if parent_id is not None else span.parent_span_id

    span.name = str(run.get("name") or span.name)
    span.span_type = span_type
    span.model = _extract_model(run) or span.model
    span.status = status
    span.error = run.get("error")
    span.input = _norm_llm_inputs(run, run.get("inputs")) or span.input
    if run.get("outputs") is not None:
        span.output = _norm_llm_outputs(run, run["outputs"])
    span.meta = _span_meta(run) or span.meta
    if run.get("start_time"):
        span.start_time = start
    if run.get("end_time"):
        span.end_time = end
        span.latency_ms = _ms(start, end)

    if span_type == "llm":
        p, c, t = _extract_tokens(run)
        span.prompt_tokens, span.completion_tokens, span.total_tokens = p, c, t
        span.cost = round(estimate_cost(span.model, p, c), 6)
        _agg_trace_totals(db, tid)

    if is_root:
        new_name = _readable_name(run)
        if new_name and new_name != str(run.get("name") or ""):
            trace.name = new_name[:200]
        trace.status = status
        trace.error = run.get("error")
        trace.input = span.input
        if run.get("outputs") is not None:
            trace.output = _norm_llm_outputs(run, run["outputs"])
        if run.get("start_time"):
            trace.start_time = start
        if run.get("end_time"):
            trace.end_time = end
            trace.latency_ms = _ms(start, end)
        if span_type == "llm":
            trace.prompt_tokens = span.prompt_tokens
            trace.completion_tokens = span.completion_tokens
            trace.total_tokens = span.total_tokens
        _agg_trace_totals(db, tid)


@router.get("/info")
def ls_info():
    return {"batch_ingest_config": {"size_limit": 100, "size_limit_bytes": 20971520,
                                    "scale_up_nthreads_limit": 4, "scale_up_qsize_trigger": 200,
                                    "scale_down_nempty_trigger": 10, "schema_type": "default"}}


@router.post("/runs/batch", status_code=202)
def ls_runs_batch(payload: dict = Body(default={}), project: Project = Depends(get_project),
                  db: Session = Depends(get_db)):
    n = 0
    for run in (payload or {}).get("post") or []:
        _apply_run(db, project, run, is_create=True)
        n += 1
    for run in (payload or {}).get("patch") or []:
        _apply_run(db, project, run, is_create=False)
        n += 1
    db.commit()
    return {"processed": n}


@router.post("/runs/multipart", status_code=202)
async def ls_runs_multipart(request: Request, project: Project = Depends(get_project),
                            db: Session = Depends(get_db)):
    """表单分片格式：post.<run_id> 主对象 + post.<run_id>.inputs/... JSON 分片。
    feedback/attachment 字段忽略（LLMTrace 反馈走自己的接口）。"""
    form = await request.form()
    runs = {"post": [], "patch": []}
    for key, value in form.multi_items():
        parts = str(key).split(".")
        if len(parts) < 2 or parts[0] not in ("post", "patch"):
            continue
        op, rid = parts[0], parts[1]
        raw = value if isinstance(value, (bytes, bytearray)) else str(value).encode()
        try:
            doc = json.loads(bytes(raw))
        except Exception:
            continue
        if len(parts) == 2:
            runs[op].append(doc)
        elif runs[op] and str(runs[op][-1].get("id")) == rid:
            runs[op][-1][parts[2]] = doc
    n = 0
    for run in runs["post"]:
        _apply_run(db, project, run, is_create=True)
        n += 1
    for run in runs["patch"]:
        _apply_run(db, project, run, is_create=False)
        n += 1
    db.commit()
    return {"processed": n}


@router.post("/runs", status_code=201)
def ls_run_create(run: dict = Body(...), project: Project = Depends(get_project),
                  db: Session = Depends(get_db)):
    _apply_run(db, project, run, is_create=True)
    db.commit()
    return {"status": "ok"}


@router.patch("/runs/{run_id}", status_code=200)
def ls_run_update(run_id: str, run: dict = Body(...), project: Project = Depends(get_project),
                  db: Session = Depends(get_db)):
    run.setdefault("id", run_id)
    _apply_run(db, project, run, is_create=False)
    db.commit()
    return {"status": "ok"}
