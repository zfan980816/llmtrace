"""Data retention: delete traces older than each project's retention window."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import Project, Span, Trace


def cleanup_expired(db: Session) -> int:
    """Delete expired traces (and their spans) per project. Returns deleted count."""
    total = 0
    for project in db.query(Project).filter(Project.retention_days > 0).all():
        cutoff = datetime.now(timezone.utc) - timedelta(days=project.retention_days)
        ids = [
            row[0]
            for row in db.query(Trace.id)
            .filter(Trace.project_id == project.id, Trace.start_time < cutoff)
            .all()
        ]
        if not ids:
            continue
        db.query(Span).filter(Span.trace_id.in_(ids)).delete(synchronize_session=False)
        db.query(Trace).filter(Trace.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        total += len(ids)
    return total


def retention_loop(interval_seconds=3600):
    """Periodic cleanup inside the backend process."""
    import time

    while True:
        time.sleep(interval_seconds)
        from ..database import SessionLocal

        db = SessionLocal()
        try:
            removed = cleanup_expired(db)
            if removed:
                print(f"[retention] removed {removed} expired traces")
        except Exception as exc:
            print(f"[retention] cleanup error: {exc}")
        finally:
            db.close()
