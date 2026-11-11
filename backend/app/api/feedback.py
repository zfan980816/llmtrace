import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Trace, TraceFeedback, User
from ..schemas import FeedbackIn, FeedbackOut
from ..services.security import get_current_user, require_admin

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


def _trace_owned(trace_id: uuid.UUID, user: User, db: Session) -> Trace:
    trace = db.get(Trace, trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return trace


@router.post("", response_model=FeedbackOut, status_code=201)
def create_feedback(
    payload: FeedbackIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.score not in (1, -1):
        raise HTTPException(status_code=422, detail="score 只能是 1 或 -1")
    if user.role == "viewer":
        raise HTTPException(status_code=403, detail="只读角色不能提交反馈")
    _trace_owned(payload.trace_id, user, db)
    fb = TraceFeedback(
        trace_id=payload.trace_id,
        user_id=user.id,
        score=payload.score,
        comment=payload.comment,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return FeedbackOut(
        id=fb.id, trace_id=fb.trace_id, score=fb.score, comment=fb.comment,
        created_at=fb.created_at, user_id=fb.user_id, user_name=user.display_name,
    )


@router.get("", response_model=list[FeedbackOut])
def list_feedback(
    trace_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _trace_owned(trace_id, user, db)
    rows = (
        db.query(TraceFeedback, User.display_name)
        .join(User, TraceFeedback.user_id == User.id)
        .filter(TraceFeedback.trace_id == trace_id)
        .order_by(TraceFeedback.created_at.desc())
        .all()
    )
    return [
        FeedbackOut(
            id=fb.id, trace_id=fb.trace_id, score=fb.score, comment=fb.comment,
            created_at=fb.created_at, user_id=fb.user_id, user_name=name,
        )
        for fb, name in rows
    ]


@router.delete("/{feedback_id}", status_code=204)
def delete_feedback(
    feedback_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fb = db.get(TraceFeedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="反馈不存在")
    if fb.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="只能删除自己的反馈")
    db.delete(fb)
    db.commit()
