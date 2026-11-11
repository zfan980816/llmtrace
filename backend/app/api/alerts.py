import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertEvent, AlertRule, Project, User
from ..schemas import AlertEventOut, AlertRuleCreate, AlertRuleOut, AlertRuleUpdate
from ..services.alerting import WEBHOOK_FORMATS, evaluate_rules
from ..services.audit import record_audit
from ..services.security import get_current_user, require_member

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

VALID_METRICS = ("error_rate", "avg_latency_ms", "p95_latency_ms")


@router.post("/rules", response_model=AlertRuleOut, status_code=201)
def create_rule(
    payload: AlertRuleCreate,
    member: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    if payload.metric_type not in VALID_METRICS:
        raise HTTPException(status_code=422, detail=f"metric_type must be one of {VALID_METRICS}")
    if payload.webhook_format not in WEBHOOK_FORMATS:
        raise HTTPException(status_code=422, detail=f"webhook_format must be one of {WEBHOOK_FORMATS}")
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rule = AlertRule(
        project_id=payload.project_id,
        name=payload.name,
        metric_type=payload.metric_type,
        threshold=payload.threshold,
        window_minutes=payload.window_minutes,
        webhook_url=payload.webhook_url,
        webhook_format=payload.webhook_format,
        webhook_secret=payload.webhook_secret,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    record_audit(db, member, "rule.create", rule.name,
                 {"metric": rule.metric_type, "threshold": rule.threshold})
    db.commit()
    return rule


@router.get("/rules", response_model=list[AlertRuleOut])
def list_rules(
    project_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(AlertRule)
    if project_id:
        q = q.filter(AlertRule.project_id == project_id)
    return q.order_by(AlertRule.created_at).all()


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
def update_rule(
    rule_id: uuid.UUID,
    payload: AlertRuleUpdate,
    member: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    record_audit(db, member, "rule.update", rule.name, changes)
    db.commit()
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: uuid.UUID,
    member: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    record_audit(db, member, "rule.delete", rule.name)
    db.commit()


@router.get("/events", response_model=list[AlertEventOut])
def list_events(
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(AlertEvent)
    if project_id:
        q = q.filter(AlertEvent.project_id == project_id)
    return q.order_by(AlertEvent.created_at.desc()).limit(min(limit, 200)).all()


@router.post("/evaluate", response_model=list[AlertEventOut])
def evaluate(
    project_id: uuid.UUID | None = None,
    member: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    return evaluate_rules(db, project_id=project_id)



