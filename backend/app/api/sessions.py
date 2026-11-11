import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..api.deps import team_projects
from ..models import Trace, User
from ..schemas import SessionOut, TraceListItem
from ..services.security import get_current_user

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionOut])
def list_sessions(
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = [Trace.session_id.isnot(None)]
    if project_id:
        filters.append(Trace.project_id == project_id)
    if allowed is not None:
        filters.append(Trace.project_id.in_(allowed))
    rows = (
        db.query(
            Trace.session_id.label("session_id"),
            func.count(Trace.id).label("trace_count"),
            func.coalesce(func.sum(Trace.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(Trace.cost), 0.0).label("total_cost"),
            func.coalesce(func.avg(Trace.latency_ms), 0).label("avg_latency_ms"),
            func.max(Trace.start_time).label("last_seen"),
        )
        .filter(*filters)
        .group_by(Trace.session_id)
        .order_by(func.max(Trace.start_time).desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        SessionOut(
            session_id=r.session_id,
            trace_count=int(r.trace_count),
            total_tokens=int(r.total_tokens),
            total_cost=round(float(r.total_cost), 6),
            avg_latency_ms=round(float(r.avg_latency_ms), 1),
            last_seen=r.last_seen,
        )
        for r in rows
    ]


@router.get("/{session_id}", response_model=list[TraceListItem])
def session_traces(
    session_id: str,
    project_id: uuid.UUID | None = None,
    allowed: list[uuid.UUID] | None = Depends(team_projects),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = [Trace.session_id == session_id]
    if project_id:
        filters.append(Trace.project_id == project_id)
    if allowed is not None:
        filters.append(Trace.project_id.in_(allowed))
    return (
        db.query(Trace)
        .filter(*filters)
        .order_by(Trace.start_time)
        .limit(500)
        .all()
    )

