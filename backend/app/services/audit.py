"""Audit trail: record who did what for key operations."""
from ..models import AuditLog, User


def record_audit(db, user: User | None, action: str, target: str = "", detail=None):
    """Add an audit entry to the session; caller is responsible for committing."""
    db.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "system",
        action=action,
        target=target[:200],
        detail=detail,
    ))
