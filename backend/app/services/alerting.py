"""Alert rule evaluation + webhook notifications."""
import hashlib
import hmac
import json
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func

from ..database import SessionLocal
from ..models import AlertEvent, AlertRule, Project, Trace

WEBHOOK_FORMATS = ("generic", "feishu", "dingtalk", "wecom")


def _window_metric(db, project_id, metric_type, since):
    """Compute a metric over [since, now]. Returns None when no data."""
    base = (Trace.project_id == project_id, Trace.start_time >= since)
    if metric_type == "error_rate":
        row = db.query(
            func.count(Trace.id).label("total"),
            func.coalesce(func.sum(case((Trace.status == "error", 1), else_=0)), 0).label("errors"),
        ).filter(*base).one()
        if not row.total:
            return None
        return float(row.errors) / float(row.total)
    if metric_type == "avg_latency_ms":
        total = db.query(func.count(Trace.id)).filter(*base).scalar()
        if not total:
            return None
        val = db.query(func.coalesce(func.avg(Trace.latency_ms), 0)).filter(*base).scalar()
        return float(val)
    if metric_type == "p95_latency_ms":
        total = db.query(func.count(Trace.id)).filter(*base).scalar()
        if not total:
            return None
        offset = min(max(int(total * 0.95), 0), total - 1)
        val = (
            db.query(Trace.latency_ms)
            .filter(*base)
            .order_by(Trace.latency_ms)
            .offset(offset)
            .limit(1)
            .scalar()
        )
        return float(val or 0)
    return None


def build_webhook_body(rule, message, generic):
    """Build provider-specific webhook payload (pure function, testable)."""
    if rule.webhook_format == "feishu":
        return {"msg_type": "text", "content": {"text": message}}
    if rule.webhook_format in ("dingtalk", "wecom"):
        return {"msgtype": "text", "text": {"content": message}}
    return generic


def sign_body(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex signature of the raw request body."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _send_webhook(rule, message, value, project_name, triggered_at):
    if not rule.webhook_url:
        return
    generic = {
        "alert": rule.name,
        "project": project_name,
        "metric": rule.metric_type,
        "value": value,
        "threshold": rule.threshold,
        "window_minutes": rule.window_minutes,
        "triggered_at": triggered_at.isoformat(),
        "message": message,
    }
    body = build_webhook_body(rule, message, generic)
    data = json.dumps(body, default=str).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if rule.webhook_secret:
        headers["X-LLMTrace-Signature"] = sign_body(rule.webhook_secret, data)
    req = urllib.request.Request(rule.webhook_url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception as exc:
        print(f"[alerting] webhook failed for rule {rule.name}: {exc}")


def evaluate_rules(db, project_id=None):
    """Evaluate all enabled rules; returns list of newly created AlertEvents."""
    now = datetime.now(timezone.utc)
    q = db.query(AlertRule).filter(AlertRule.enabled.is_(True))
    if project_id:
        q = q.filter(AlertRule.project_id == project_id)

    events = []
    for rule in q.all():
        since = now - timedelta(minutes=rule.window_minutes)
        value = _window_metric(db, rule.project_id, rule.metric_type, since)
        if value is None or value < rule.threshold:
            continue

        recent = (
            db.query(AlertEvent)
            .filter(AlertEvent.rule_id == rule.id, AlertEvent.created_at >= since)
            .first()
        )
        if recent:
            continue  # cooldown: skip if already triggered within the window

        project = db.query(Project).filter(Project.id == rule.project_id).first()
        project_name = project.name if project else "?"
        message = (
            f"[LLMTrace] 规则「{rule.name}」触发: "
            f"{rule.metric_type}={value:.4f} >= {rule.threshold} "
            f"(窗口 {rule.window_minutes} 分钟)"
        )
        event = AlertEvent(
            project_id=rule.project_id,
            rule_id=rule.id,
            rule_name=rule.name,
            metric_type=rule.metric_type,
            value=round(value, 6),
            threshold=rule.threshold,
            message=message,
        )
        db.add(event)
        db.commit()
        events.append(event)
        threading.Thread(
            target=_send_webhook,
            args=(rule, message, value, project_name, now),
            daemon=True,
        ).start()
    return events


def background_loop(interval_seconds=60):
    """Periodic evaluator run inside the backend process."""
    while True:
        time.sleep(interval_seconds)
        db = SessionLocal()
        try:
            evaluate_rules(db)
        except Exception as exc:
            print(f"[alerting] evaluate error: {exc}")
        finally:
            db.close()

