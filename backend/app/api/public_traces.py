"""Public trace share view - no auth required, share_token is the capability."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, Trace
from ..schemas import TraceOut

router = APIRouter(prefix="/api/v1/public/traces", tags=["public"])


@router.get("/{share_token}", response_model=TraceOut)
def get_shared_trace(share_token: str, db: Session = Depends(get_db)):
    row = (
        db.query(Trace, Project)
        .join(Project, Trace.project_id == Project.id)
        .filter(Trace.share_token == share_token)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="share link invalid or revoked")
    trace, project = row
    return trace
