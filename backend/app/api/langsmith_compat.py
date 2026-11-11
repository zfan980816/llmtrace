# -*- coding: utf-8 -*-
"""LangSmith 兼容接入端点：LangChain 内置 tracer 零代码直连 LLMTrace。

LangSmith Python SDK（langsmith>=0.2）以 JSON 批量方式上报 run：
  POST /runs/batch        body={"post": [run...], "patch": [run...]}（主路径）
  POST /runs              单条 create
  PATCH /runs/{id}        单条 update
  GET  /info              客户端启动探测批量配置
run 是 LangChain 的通用 span（run_type: chain/llm/tool/retriever/embedding...）。

映射策略（无内存状态、重启/多 worker 安全、trace 实时更新）：
  Trace.id  = LangSmith trace_id（根 run 的 id，get_or_create 按主键幂等）
  Span.id   = LangSmith run id（天然幂等 upsert 键）
  Span.trace_id = run["trace_id"]；Span.parent_span_id = run["parent_run_id"]
子 run 落库时父 span 按主键可查；根 run 结束（patch 带 end_time）时回填 trace
汇总字段（output/status/latency/token 聚合）。

用户侧配置（零代码）：
  LANGSMITH_TRACING=true
  LANGSMITH_ENDPOINT=http://<llmtrace-host>:8000
  LANGSMITH_API_KEY=<LLMTrace 项目 API Key>
"""

import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..api.deps import get_project
from ..services.cost import estimate_cost
from ..database import get_db
from ..models import Project, Span, Trace

router = APIRouter(tags=["langsmith-compat"])

# LangSmith run_type → LLMTrace span_type
_SPAN_TYPES = {"llm": "llm", "chat_model": "llm", "tool": "tool",
               "retriever": "retrieval", "embedding": "embedding",
               "agent": "agent", "chain": "chain"}


def _parse_dt(v):
    """ISO 字符串/None → aware datetime（UTC）。LangSmith 客户端发 isoformat 字符串。"""
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


_GENERIC_ROOT_NAMES = {"langgraph", "langchain", "chain", "agent", "agentexecutor",
                       "runnablesequence", "runnable", "router", "executor"}


def _short_label(text, cap=20):
    """提取「领域名」做列表展示：
    「景点地址：上海 酒店地址：…」→ 冒号前主语「景点地址」；
    无冒号取首个逗号短句「北京出发去上海玩3天」——都是领域主语，不是句子片段。"""
    s = re.sub(r"\s+", " ", str(text)).strip()
    if not s:
        return ""
    seg = re.split(r"[。！？!?；;\n]", s)[0].strip() or s
    colons = [i for i in (seg.find("："), seg.find(":")) if i >= 0]
    if colons:  # 「键：值 …」→ 领域名 = 冒号前的主语
        key = seg[:min(colons)].strip()
        if 2 <= len(key) <= 12:
            return key
    first = re.split(r"[，,、]", seg)[0].strip()
    if len(first) >= 4:
        seg = first  # 首个逗号短句即领域主语
    if len(seg) > cap:
        seg = seg[:cap] + "…"
    return seg


def _readable_name(run):
    """根 trace 的可读名：LangGraph/ChatOpenAI 这类框架内部名没业务含义，
    从 inputs 里挖第一条人类消息或主要文本字段（LangSmith 同款体验）。"""
    name = str(run.get("name") or "")
    is_llm_root = str(run.get("run_type") or "") in ("llm", "chat_model")
    if name.lower() not in _GENERIC_ROOT_NAMES and not is_llm_root:
        # chain 根按名单判定；llm 根（ChatOpenAI 等模型类名）一律尝试挖可读文本
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
    for v in ins.values():  # 兜底：state dict 里第一条字符串值
        if isinstance(v, str) and v.strip():
            return _short_label(v)
    return name or "trace"


def _extra_meta(run):
    """extra.metadata（langchain 的 ls_* 字段/用户 metadata 都在这里）。"""
    extra = run.get("extra") or {}
    md = extra.get("metadata") or {}
    return md if isinstance(md, dict) else {}


def _unwrap_msg(m):
    """langchain 序列化消息 → {role, content, ...}。
    兼容两种形态：lc constructor（{"lc":1,"type":"constructor","kwargs":{...}}）
    与纯 dict（{"role"/"type": ..., "content": ...}）。"""
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
    md = _extra_meta(run)
    model = md.get("ls_model_name")
    if not model:
        ser = run.get("serialized") or {}
        model = (ser.get("kwargs") or {}).get("model") if isinstance(ser, dict) else None
    return model


def _extract_tokens(run):
    """token 数多来源兜底：顶层字段 → outputs.token_usage / outputs.llm_output.token_usage。"""
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
    """LLM run 的 inputs 形如 {"messages": [[msg, ...]]}（batch 套一层）→ 摊平供前端气泡渲染。"""
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
    """LLM run 的 outputs 形如 {"generations": [[gen...]]} → 转成 {"messages": [...]}
    （前端 Output 气泡视图可直接渲染；其他形状原样保留走 Raw JSON）。"""
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
    """用 spans 聚合回填 trace 的 token/成本汇总（与 SDK 上报口径一致：token 全 span 求和，成本只算 llm span）。"""
    db.flush()  # autoflush=False：先把 pending 的 span 变更刷进事务，聚合才读得到
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
    """单个 run 的 upsert：post 建行、patch 更新；幂等（按主键）。"""
    try:
        rid = uuid.UUID(str(run["id"]))
        tid = uuid.UUID(str(run.get("trace_id") or run["id"]))
    except (KeyError, ValueError):
        return  # 缺 id/非法：跳过，不让单条坏数据毁掉整批
    start = _parse_dt(run.get("start_time")) or datetime.now(timezone.utc)
    end = _parse_dt(run.get("end_time")) or start
    status = "error" if run.get("error") else "ok"
    raw_type = str(run.get("run_type") or "chain")
    span_type = _SPAN_TYPES.get(raw_type, "chain")
    parent_id = uuid.UUID(str(run["parent_run_id"])) if run.get("parent_run_id") else None
    is_root = parent_id is None

    # langgraph 结构细分：chain 名字蕴含真实角色——主图/子图=agent，model=llm 步骤，
    # tools=工具步骤，tools 的子 run=具体工具调用（LangSmith 同款阅读体验）
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

    # ---- trace 行（按主键 get_or_create：根 run 先到先建；子 run 先到也能兜底建壳）----
    trace = db.get(Trace, tid)
    if trace is None:
        md = _extra_meta(run)
        trace = Trace(
            id=tid, project_id=project.id,
            name=_readable_name(run)[:200],
            session_id=(md.get("thread_id") and str(md["thread_id"])) or None,
            status="ok", error=None,
            input=_norm_llm_inputs(run, run.get("inputs")),
            output=None, meta={"langsmith_project": run.get("session_name") or None,
                               "ls_trace_id": str(tid)},
            start_time=start, end_time=end, latency_ms=0,
        )
        db.add(trace)
        db.flush()

    # ---- span 行（pk = run id，天然幂等）----
    span = db.get(Span, rid)
    if span is None:
        if not is_create:
            return  # patch 先于 post（乱序重试边缘）：丢弃，post 会带全量字段
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

    # ---- patch/重复 post 的字段回填（含结束时才有的字段）----
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
        span.start_time = start  # patch 通常不带 start_time，缺省保留原值防漂移
    if run.get("end_time"):
        span.end_time = end
        span.latency_ms = _ms(start, end)

    if span_type == "llm":
        p, c, t = _extract_tokens(run)
        span.prompt_tokens, span.completion_tokens, span.total_tokens = p, c, t
        span.cost = round(estimate_cost(span.model, p, c), 6)
        _agg_trace_totals(db, tid)

    # ---- 根 run：镜像回填 trace 汇总字段（LangSmith 同款语义）----
    if is_root:
        new_name = _readable_name(run)
        if new_name and new_name != str(run.get("name") or ""):
            # 仅当提取到可读名（patch 不带 inputs 时 _readable_name 退回框架名，不覆盖创建时的好名）
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
    """langsmith Client 启动时探测批量配置（真实 LangSmith 同款端点）。"""
    # 客户端后台线程硬依赖这些 key（_background_thread.py 直接 [] 取值），缺一会崩
    return {"batch_ingest_config": {"size_limit": 100, "size_limit_bytes": 20971520,
                                    "scale_up_nthreads_limit": 4, "scale_up_qsize_trigger": 200,
                                    "scale_down_nempty_trigger": 10, "schema_type": "default"}}


@router.post("/runs/batch", status_code=202)
def ls_runs_batch(payload: dict = Body(default={}), project: Project = Depends(get_project),
                  db: Session = Depends(get_db)):
    """主上报路径：{"post": [run...], "patch": [run...]}。逐条 upsert，坏数据跳过不毁整批。"""
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
    """现代客户端默认路径（requests files= 表单）：
    字段名 "post.<run_id>" 为主对象，"post.<run_id>.inputs/outputs/..." 为对应 JSON 分片；
    feedback/attachment 字段安全忽略（LLMTrace 反馈走自己的 RBAC 接口）。"""
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
            continue  # 坏分片跳过，不毁整批
        if len(parts) == 2:
            runs[op].append(doc)
        elif runs[op] and str(runs[op][-1].get("id")) == rid:
            runs[op][-1][parts[2]] = doc  # 分片挂到紧邻前方的同 id 主对象上
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
    """单条 create（部分客户端/旧版本路径）。"""
    _apply_run(db, project, run, is_create=True)
    db.commit()
    return {"status": "ok"}


@router.patch("/runs/{run_id}", status_code=200)
def ls_run_update(run_id: str, run: dict = Body(...), project: Project = Depends(get_project),
                  db: Session = Depends(get_db)):
    """单条 update。"""
    run.setdefault("id", run_id)
    _apply_run(db, project, run, is_create=False)
    db.commit()
    return {"status": "ok"}
