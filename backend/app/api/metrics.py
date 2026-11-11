import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Span, Trace, User
from ..schemas import ErrorClusterOut, HistogramBucket, ModelStatOut, OverviewOut, TimePoint
from ..services.security import get_current_user

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


def _as_utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("/overview", response_model=OverviewOut)
def overview(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    filters = [Trace.start_time >= since]
    if project_id:
        filters.append(Trace.project_id == project_id)
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

    rows = db.query(
        bucket,
        func.count(Trace.id).label("calls"),
        func.coalesce(func.sum(case((Trace.status == "error", 1), else_=0)), 0).label("errors"),
        func.coalesce(func.avg(Trace.latency_ms), 0).label("avg_latency"),
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
            tokens=int(r.tokens) if r else 0,
            cost=round(float(r.cost), 6) if r else 0.0,
        ))
    return points



@router.get("/models", response_model=list[ModelStatOut])
def model_stats(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按模型聚合 LLM span：调用数 / token / 成本 / 平均延迟。"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    filters = [Span.span_type == "llm", Span.start_time >= since]
    if project_id:
        filters.append(Trace.project_id == project_id)
    rows = (
        db.query(
            Span.model.label("model"),
            func.count(Span.id).label("calls"),
            func.coalesce(func.sum(Span.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(Span.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(Span.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(Span.cost), 0.0).label("cost"),
            func.coalesce(func.avg(Span.latency_ms), 0).label("avg_latency"),
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
        )
        for r in rows
    ]


@router.get("/latency-histogram", response_model=list[HistogramBucket])
def latency_histogram(
    hours: int = Query(24, ge=1, le=720),
    buckets: int = Query(20, ge=5, le=60),
    project_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trace 延迟分布直方图。"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    filters = [Trace.start_time >= since]
    if project_id:
        filters.append(Trace.project_id == project_id)
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


@router.get("/errors", response_model=list[ErrorClusterOut])
def error_clusters(
    hours: int = Query(24, ge=1, le=720),
    project_id: uuid.UUID | None = None,
    top: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """错误聚类 Top N：按 error 文本聚合失败 trace。"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(Trace).filter(Trace.status == "error", Trace.start_time >= since)
    if project_id:
        q = q.filter(Trace.project_id == project_id)
    rows = q.order_by(Trace.start_time.desc()).limit(2000).all()
    clusters: dict[str, dict] = {}
    for t in rows:
        key = (t.error or "（未记录错误详情）")[:160]
        c = clusters.setdefault(key, {"count": 0, "last_seen": t.start_time,
                                      "sample_trace_id": t.id, "sample_name": t.name})
        c["count"] += 1
    items = sorted(clusters.items(), key=lambda kv: kv[1]["count"], reverse=True)[:top]
    return [
        ErrorClusterOut(error=k, count=v["count"], last_seen=v["last_seen"],
                        sample_trace_id=v["sample_trace_id"], sample_name=v["sample_name"])
        for k, v in items
    ]
