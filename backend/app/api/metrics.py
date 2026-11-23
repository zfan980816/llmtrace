import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..api.deps import team_projects
from ..models import Span, Trace, User
from ..schemas import (
    ErrorClusterOut,
    HistogramBucket,
    LatencyBreakdown,
    LatencyPart,
    ModelStatOut,
    OverviewOut,
    SlowTrace,
    TimePoint,
)
from ..services.security import get_current_user

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


def _as_utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("/overview", response_model=OverviewOut)
def overview(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    filters = [Trace.start_time >= since]
    if project_id:
        filters.append(Trace.project_id == project_id)
    if allowed is not None:
        filters.append(Trace.project_id.in_(allowed))
    base = tuple(filters)

    row = db.query(
        func.count(Trace.id).label("total"),
        func.coalesce(func.sum(case((Trace.status == "error", 1), else_=0)), 0).label("errors"),
        func.coalesce(func.avg(Trace.latency_ms), 0).label("avg_latency"),
        func.coalesce(func.sum(Trace.total_tokens), 0).label("tokens"),
        func.coalesce(func.sum(Trace.cost), 0.0).label("cost"),
    ).filter(*base).one()

    total = int(row.total)
    errors = int(row.errors)
    p95 = 0.0
    if total:
        offset = min(max(int(total * 0.95), 0), total - 1)
        val = (
            db.query(Trace.latency_ms)
            .filter(*base)
            .order_by(Trace.latency_ms)
            .offset(offset)
            .limit(1)
            .scalar()
        )
        p95 = float(val or 0)

    return OverviewOut(
        total_traces=total,
        total_errors=errors,
        error_rate=(errors / total) if total else 0.0,
        avg_latency_ms=round(float(row.avg_latency), 1),
        p95_latency_ms=p95,
        total_tokens=int(row.tokens),
        total_cost=round(float(row.cost), 6),
    )


@router.get("/timeseries", response_model=list[TimePoint])
def timeseries(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    is_sqlite = db.bind.dialect.name == "sqlite"
    if is_sqlite:
        bucket = func.strftime("%Y-%m-%dT%H:00:00", Trace.start_time).label("bucket")
    else:
        bucket = func.date_trunc("hour", Trace.start_time).label("bucket")

    filters = [Trace.start_time >= since]
    if project_id:
        filters.append(Trace.project_id == project_id)
    if allowed is not None:
        filters.append(Trace.project_id.in_(allowed))

    if is_sqlite:
        # sqlite 无 percentile_cont，开发库用均值兜底
        p50 = func.coalesce(func.avg(Trace.latency_ms), 0).label("p50")
        p95 = func.coalesce(func.avg(Trace.latency_ms), 0).label("p95")
    else:
        p50 = func.coalesce(func.percentile_cont(0.5).within_group(Trace.latency_ms.asc()), 0).label("p50")
        p95 = func.coalesce(func.percentile_cont(0.95).within_group(Trace.latency_ms.asc()), 0).label("p95")

    rows = db.query(
        bucket,
        func.count(Trace.id).label("calls"),
        func.coalesce(func.sum(case((Trace.status == "error", 1), else_=0)), 0).label("errors"),
        func.coalesce(func.avg(Trace.latency_ms), 0).label("avg_latency"),
        p50,
        p95,
        func.coalesce(func.sum(Trace.total_tokens), 0).label("tokens"),
        func.coalesce(func.sum(Trace.cost), 0.0).label("cost"),
    ).filter(*filters).group_by(bucket).order_by(bucket).all()

    def _bucket_key(b):
        return _as_utc(datetime.fromisoformat(b)) if isinstance(b, str) else _as_utc(b)

    by_bucket = {_bucket_key(r.bucket): r for r in rows}
    hour0 = since.replace(minute=0, second=0, microsecond=0)
    points = []
    for i in range(hours + 1):
        t = hour0 + timedelta(hours=i)
        r = by_bucket.get(t)
        points.append(TimePoint(
            bucket=t,
            calls=int(r.calls) if r else 0,
            errors=int(r.errors) if r else 0,
            avg_latency_ms=round(float(r.avg_latency), 1) if r else 0.0,
            p50_latency_ms=round(float(r.p50), 1) if r and r.calls else 0.0,
            p95_latency_ms=round(float(r.p95), 1) if r and r.calls else 0.0,
            tokens=int(r.tokens) if r else 0,
            cost=round(float(r.cost), 6) if r else 0.0,
        ))
    return points



@router.get("/models", response_model=list[ModelStatOut])
def model_stats(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按模型聚合 LLM span：调用数 / token / 成本 / 平均延迟。"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    filters = [Span.span_type == "llm", Span.start_time >= since]
    if project_id:
        filters.append(Trace.project_id == project_id)
    if allowed is not None:
        filters.append(Trace.project_id.in_(allowed))
    rows = (
        db.query(
            Span.model.label("model"),
            func.count(Span.id).label("calls"),
            func.coalesce(func.sum(Span.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(Span.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(Span.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(Span.cost), 0.0).label("cost"),
            func.coalesce(func.avg(Span.latency_ms), 0).label("avg_latency"),
            func.coalesce(func.sum(Span.latency_ms), 0).label("total_latency"),
        )
        .join(Trace, Span.trace_id == Trace.id)
        .filter(*filters)
        .group_by(Span.model)
        .order_by(func.sum(Span.cost).desc())
        .all()
    )
    return [
        ModelStatOut(
            model=r.model or "unknown",
            calls=int(r.calls),
            prompt_tokens=int(r.prompt_tokens),
            completion_tokens=int(r.completion_tokens),
            total_tokens=int(r.total_tokens),
            cost=round(float(r.cost), 6),
            avg_latency_ms=round(float(r.avg_latency), 1),
            output_tps=round(int(r.completion_tokens) / (float(r.total_latency) / 1000), 1) if r.total_latency else 0.0,
        )
        for r in rows
    ]


@router.get("/latency-histogram", response_model=list[HistogramBucket])
def latency_histogram(
    hours: int = Query(24, ge=1, le=720),
    buckets: int = Query(20, ge=5, le=60),
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trace 延迟分布直方图。"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    filters = [Trace.start_time >= since]
    if project_id:
        filters.append(Trace.project_id == project_id)
    if allowed is not None:
        filters.append(Trace.project_id.in_(allowed))
    vals = [v for (v,) in db.query(Trace.latency_ms).filter(*filters).limit(20000).all() if v is not None]
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    width = max((hi - lo) / buckets, 1)
    counts = [0] * buckets
    for v in vals:
        idx = min(int((v - lo) / width), buckets - 1)
        counts[idx] += 1
    return [
        HistogramBucket(label=str(int(lo + i * width)) + "-" + str(int(lo + (i + 1) * width)), count=c)
        for i, c in enumerate(counts)
    ]


@router.get("/latency-breakdown", response_model=LatencyBreakdown)
def latency_breakdown(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """耗时构成：延迟花在了 LLM 生成、工具调用还是编排上。

    每个 span 取"独占时间" = 自身时长 - 直接子节点时长之和，这样中间件包装层
    （时长与内部 LLM 调用相同）不会被重复计入。
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    filters = [Span.start_time >= since]
    if project_id:
        filters.append(Trace.project_id == project_id)
    if allowed is not None:
        filters.append(Trace.project_id.in_(allowed))

    limit = 50000
    rows = (
        db.query(
            Span.trace_id, Span.id, Span.parent_span_id, Span.span_type, Span.latency_ms,
        )
        .join(Trace, Span.trace_id == Trace.id)
        .filter(*filters)
        .order_by(Span.start_time.desc())
        .limit(limit + 1)
        .all()
    )
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    by_trace = {}
    for r in rows:
        by_trace.setdefault(r.trace_id, []).append(r)

    def kind(span_type):
        if span_type in ("llm", "embedding"):
            return "llm"
        if span_type in ("tool", "retrieval"):
            return "tool"
        return "other"

    totals = {"llm": 0.0, "tool": 0.0, "other": 0.0}
    counts = {"llm": 0, "tool": 0, "other": 0}
    traces = 0
    for spans in by_trace.values():
        # 被截断的 trace 缺少根节点，跳过，避免统计到半条链路
        if not any(s.parent_span_id is None for s in spans):
            continue
        child_sum = {}
        for s in spans:
            if s.parent_span_id is not None and s.latency_ms:
                child_sum[s.parent_span_id] = child_sum.get(s.parent_span_id, 0) + s.latency_ms
        traces += 1
        for s in spans:
            own = max(0.0, (s.latency_ms or 0) - child_sum.get(s.id, 0))
            k = kind(s.span_type)
            totals[k] += own
            if s.latency_ms:
                counts[k] += 1

    total = sum(totals.values())
    return LatencyBreakdown(
        traces=traces,
        parts=[
            LatencyPart(
                key=k, ms=round(totals[k], 1),
                pct=round(totals[k] / total * 100, 1) if total else 0.0,
                per_trace_ms=round(totals[k] / traces, 1) if traces else 0.0,
                spans=counts[k],
            )
            for k in ("llm", "tool", "other")
        ],
    )


@router.get("/slowest", response_model=list[SlowTrace])
def slowest_traces(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """所选时间内最慢的 trace，用于定位瓶颈。"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    filters = [Trace.start_time >= since, Trace.latency_ms.isnot(None)]
    if project_id:
        filters.append(Trace.project_id == project_id)
    if allowed is not None:
        filters.append(Trace.project_id.in_(allowed))
    rows = (
        db.query(Trace)
        .filter(*filters)
        .order_by(Trace.latency_ms.desc())
        .limit(limit)
        .all()
    )
    return [
        SlowTrace(
            id=str(r.id), name=r.name, latency_ms=int(r.latency_ms),
            start_time=r.start_time, status=r.status,
            total_tokens=int(r.total_tokens or 0),
        )
        for r in rows
    ]


_STATUS_PREFIXES = ("code: ", "status: ", "status_code: ", "status_code=", "HTTP ")


def _keep_status_code(m):
    before = m.string[max(0, m.start() - 16):m.start()]
    return m.group(0) if before.endswith(_STATUS_PREFIXES) else "<n>"


# 错误聚类前抹掉易变部分：路径、UUID、行号、长 ID 等，只保留错误类型和结构
_ERROR_NOISE = (
    (re.compile(r"\b(?:https?|wss?)://[^\s\"'<>]+"), "<url>"),
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<uuid>"),
    (re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\s\"']*"), "<path>"),
    (re.compile(r"(?<![\w:])/(?:[\w.\-]+/)+[\w.\-]*"), "<path>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),
    (re.compile(r"\b[A-Za-z0-9_\-]{24,}\b"), "<id>"),
    # 行号、耗时等数字归一；HTTP 状态码（code: 429 / HTTP 500）保留，它们区分错误类别
    (re.compile(r"\d+"), _keep_status_code),
)
_PLACEHOLDER = re.compile(r"<(?:url|uuid|path|addr|id|n)>")
_TRACEBACK = "Traceback (most recent call last)"


def _error_head(text):
    """只取异常本身，不带调用栈：栈里的路径、行号会随应用版本变，对聚类没用。
    LangGraph 把异常写在栈前面，Python 标准格式写在最后。"""
    s = (text or "").strip()
    if _TRACEBACK not in s:
        return s
    head = s.split(_TRACEBACK, 1)[0].strip()
    return head or s.rsplit("\n", 1)[-1].strip()


def _error_signature(head):
    s = head or ""
    for rx, rep in _ERROR_NOISE:
        s = rx.sub(rep, s)
    return re.sub(r"\s+", " ", s).strip()[:160] or "（未记录错误详情）"


def _cluster_search(sig):
    """从签名里挑最长的一段字面量，跳到 trace 列表时用它搜索，能把整类错误搜出来。"""
    tokens = [t for seg in _PLACEHOLDER.split(sig) for t in seg.split() if "%" not in t]
    return max(tokens, key=len, default="")


@router.get("/errors", response_model=list[ErrorClusterOut])
def error_clusters(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    top: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """错误聚类 Top N：按归一化后的异常行聚合失败的 trace，展示最近一条的异常行。"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(Trace).filter(Trace.status == "error", Trace.start_time >= since)
    if project_id:
        q = q.filter(Trace.project_id == project_id)
    if allowed is not None:
        q = q.filter(Trace.project_id.in_(allowed))
    rows = q.order_by(Trace.start_time.desc()).limit(2000).all()
    clusters: dict[str, dict] = {}
    for t in rows:
        head = _error_head(t.error)
        key = _error_signature(head)
        c = clusters.setdefault(key, {"count": 0, "last_seen": t.start_time,
                                      "sample_trace_id": t.id, "sample_name": t.name,
                                      "sample": head or "（未记录错误详情）"})
        c["count"] += 1
    items = sorted(clusters.items(), key=lambda kv: kv[1]["count"], reverse=True)[:top]
    return [
        ErrorClusterOut(error=v["sample"], count=v["count"], last_seen=v["last_seen"],
                        sample_trace_id=v["sample_trace_id"], sample_name=v["sample_name"],
                        search=_cluster_search(k) or None)
        for k, v in items
    ]
