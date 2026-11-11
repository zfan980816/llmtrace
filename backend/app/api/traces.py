import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, func, or_
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .deps import get_project
from ..database import get_db
from ..api.deps import team_projects
from ..models import Project, Span, Trace, User
from ..schemas import TraceBatchIn, TraceIn, TraceListItem, TraceOut, TracePageOut, RunListItem, RunPageOut
from ..services.cost import estimate_cost
from ..services.masking import mask_pii
from ..services.security import get_current_user
from ..services.ws import notify_trace

router = APIRouter(prefix="/api/v1/traces", tags=["traces"])


def _persist_trace(payload: TraceIn, project: Project, db: Session) -> Trace:
    """Validate + mask + add one trace (with spans) to the session. Caller commits."""
    root = next((s for s in payload.spans if s.parent_span_id is None), None)
    name = payload.name or (root.name if root else "trace")
    start = payload.start_time or (root.start_time if root else None)
    end = payload.end_time or (root.end_time if root else None)
    if start is None or end is None:
        raise HTTPException(status_code=422, detail="start_time/end_time required")

    mask = project.mask_pii
    trace_input = payload.input if payload.input is not None else (root.input if root else None)
    trace_output = payload.output if payload.output is not None else (root.output if root else None)
    if mask:
        trace_input = mask_pii(trace_input) if trace_input is not None else None
        trace_output = mask_pii(trace_output) if trace_output is not None else None

    prompt_tokens = sum(s.prompt_tokens for s in payload.spans)
    completion_tokens = sum(s.completion_tokens for s in payload.spans)
    total_tokens = sum(s.total_tokens for s in payload.spans) or prompt_tokens + completion_tokens
    cost = sum(
        estimate_cost(s.model, s.prompt_tokens, s.completion_tokens)
        for s in payload.spans
        if s.span_type == "llm"
    )

    trace = Trace(
        project_id=project.id,
        name=name[:200],
        session_id=payload.session_id,
        status=payload.status,
        error=payload.error,
        input=trace_input,
        output=trace_output,
        meta=mask_pii(payload.metadata) if mask and payload.metadata else payload.metadata,
        start_time=start,
        end_time=end,
        latency_ms=int((end - start).total_seconds() * 1000),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost=cost,
    )
    db.add(trace)
    db.flush()

    for s in payload.spans:
        span_id = s.id if s.id is not None else uuid.uuid4()
        # 服务端智能错误推断：显式上报优先；否则输出含 error 键或失败 trace 的根 span 标记为 error
        span_status, span_error = s.status, s.error
        if span_status != "error":
            if isinstance(s.output, dict) and "error" in s.output:
                span_status = "error"
                if span_error is None:
                    span_error = json.dumps(s.output["error"], ensure_ascii=False)
            elif payload.status == "error" and s.parent_span_id is None:
                span_status = "error"
        db.add(Span(
            id=span_id,
            trace_id=trace.id,
            parent_span_id=s.parent_span_id,
            name=s.name[:200],
            span_type=s.span_type[:20],
            model=s.model,
            status=span_status,
            error=span_error,
            input=mask_pii(s.input) if mask and s.input is not None else s.input,
            output=mask_pii(s.output) if mask and s.output is not None else s.output,
            meta=mask_pii(s.metadata) if mask and s.metadata is not None else s.metadata,
            prompt_tokens=s.prompt_tokens,
            completion_tokens=s.completion_tokens,
            total_tokens=s.total_tokens,
            cost=estimate_cost(s.model, s.prompt_tokens, s.completion_tokens) if s.span_type == "llm" else 0.0,
            start_time=s.start_time,
            end_time=s.end_time,
            latency_ms=int((s.end_time - s.start_time).total_seconds() * 1000),
        ))
    return trace


@router.post("/ingest", status_code=201)
def ingest(payload: TraceIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """SDK 单条上报：X-API-Key 鉴权。"""
    trace = _persist_trace(payload, project, db)
    db.commit()
    notify_trace(project.id, trace.id, trace.name, trace.status)
    return {"id": str(trace.id)}


@router.post("/ingest-batch", status_code=201)
def ingest_batch(payload: TraceBatchIn, project: Project = Depends(get_project), db: Session = Depends(get_db)):
    """SDK 批量上报：一次请求写入多条 trace。"""
    ids = []
    for t in payload.traces:
        tr = _persist_trace(t, project, db)
        ids.append(str(tr.id))
        notify_trace(project.id, tr.id, tr.name, tr.status)
    db.commit()
    return {"count": len(ids), "ids": ids}


@router.get("/export")
def export_traces(
    format: str = "csv",
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出最近 5000 条 trace（列表级字段，不含 span 明细）。"""
    fmt = (format or "csv").lower()
    if fmt not in ("csv", "json"):
        raise HTTPException(status_code=422, detail="format must be csv or json")
    q = db.query(Trace)
    if project_id:
        q = q.filter(Trace.project_id == project_id)
    if allowed is not None:
        q = q.filter(Trace.project_id.in_(allowed))
    traces = q.order_by(Trace.start_time.desc()).limit(5000).all()

    cols = ["id", "name", "session_id", "status", "error", "start_time", "end_time",
            "latency_ms", "prompt_tokens", "completion_tokens", "total_tokens", "cost"]

    if fmt == "json":
        data = []
        for t in traces:
            row = {c: getattr(t, c) for c in cols}
            for k in ("start_time", "end_time"):
                row[k] = row[k].isoformat()
            data.append(row)
        return Response(
            content=json.dumps(data, ensure_ascii=False, default=str),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=traces.json"},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for t in traces:
        writer.writerow([getattr(t, c) for c in cols])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=traces.csv"},
    )


@router.get("", response_model=TracePageOut)
def list_traces(
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    status: str | None = None,
    model: str | None = None,
    span_type: str | None = None,
    min_latency: int | None = None,
    max_latency: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Trace)
    if project_id:
        query = query.filter(Trace.project_id == project_id)
    if allowed is not None:
        query = query.filter(Trace.project_id.in_(allowed))
    if status:
        query = query.filter(Trace.status == status)
    if min_latency is not None:
        query = query.filter(Trace.latency_ms >= min_latency)
    if max_latency is not None:
        query = query.filter(Trace.latency_ms <= max_latency)
    if model:
        query = query.filter(Trace.id.in_(db.query(Span.trace_id).filter(Span.model == model)))
    if span_type:
        query = query.filter(Trace.id.in_(db.query(Span.trace_id).filter(Span.span_type == span_type)))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Trace.name.ilike(like),
            Trace.session_id.ilike(like),
            Trace.error.ilike(like),
            func.cast(Trace.input, String).ilike(like),
            func.cast(Trace.output, String).ilike(like),
        ))
    total = query.count()
    items = query.order_by(Trace.start_time.desc()).offset(offset).limit(min(limit, 200)).all()
    return TracePageOut(items=items, total=total)


@router.get("/runs", response_model=RunPageOut)
def list_runs(
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    span_type: str | None = None,
    model: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """跨 trace 的 run（span）平铺列表，LangSmith Runs 视图。"""
    query = db.query(Span, Trace).join(Trace, Span.trace_id == Trace.id)
    if project_id is not None:
        query = query.filter(Trace.project_id == project_id)
    if allowed is not None:
        query = query.filter(Trace.project_id.in_(allowed))
    if span_type:
        query = query.filter(Span.span_type == span_type)
    if model:
        query = query.filter(Span.model.ilike(f"%{model}%"))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Span.name.ilike(like),
            Span.error.ilike(like),
            func.cast(Span.input, String).ilike(like),
            func.cast(Span.output, String).ilike(like),
            Trace.name.ilike(like),
        ))
    total = query.count()
    rows = query.order_by(Span.start_time.desc()).limit(min(limit, 200)).offset(offset).all()
    items = []
    for span, trace in rows:
        item = RunListItem(
            id=span.id, name=span.name, span_type=span.span_type, model=span.model,
            status=span.status, latency_ms=span.latency_ms,
            prompt_tokens=span.prompt_tokens, completion_tokens=span.completion_tokens,
            cost=span.cost, start_time=span.start_time,
            input=span.input, output=span.output, error=span.error,
            trace_id=trace.id, trace_name=trace.name, session_id=trace.session_id,
        )
        items.append(item)
    return {"items": items, "total": total}


@router.get("/{trace_id}", response_model=TraceOut)
def get_trace(
    trace_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    trace = db.get(Trace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace
