from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import uuid as _uuid

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    api_key: str
    mask_pii: bool
    retention_days: int
    created_at: datetime


class SpanIn(BaseModel):
    id: Optional[UUID] = None
    parent_span_id: Optional[UUID] = None
    name: str
    span_type: str = "chain"
    model: Optional[str] = None
    status: str = "ok"
    error: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    metadata: Optional[dict[str, Any]] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    start_time: datetime
    end_time: datetime


class TraceIn(BaseModel):
    name: Optional[str] = None
    session_id: Optional[str] = None
    status: str = "ok"
    error: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    metadata: Optional[dict[str, Any]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    spans: list[SpanIn] = Field(default_factory=list)


class SpanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_span_id: Optional[UUID]
    name: str
    span_type: str
    model: Optional[str]
    status: str
    error: Optional[str]
    input: Optional[Any]
    output: Optional[Any]
    meta: Optional[Any] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    start_time: datetime
    end_time: datetime
    latency_ms: int


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    session_id: Optional[str]
    status: str
    error: Optional[str]
    input: Optional[Any]
    output: Optional[Any]
    meta: Optional[Any] = None
    start_time: datetime
    end_time: datetime
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    spans: list[SpanOut] = []


class TraceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    session_id: Optional[str]
    status: str
    start_time: datetime
    latency_ms: int
    total_tokens: int
    cost: float
    input: Optional[Any] = None
    output: Optional[Any] = None
    error: Optional[str] = None


class RunListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    span_type: str
    model: Optional[str] = None
    status: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    cost: float
    start_time: datetime
    input: Optional[Any] = None
    output: Optional[Any] = None
    error: Optional[str] = None
    trace_id: UUID
    trace_name: str
    session_id: Optional[str] = None


class RunPageOut(BaseModel):
    items: list[RunListItem]
    total: int


class FeedbackIn(BaseModel):
    trace_id: UUID
    score: int  # 1 or -1
    comment: Optional[str] = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: UUID
    score: int
    comment: Optional[str] = None
    created_at: datetime
    user_id: UUID
    user_name: Optional[str] = None


class ErrorClusterOut(BaseModel):
    error: str
    count: int
    last_seen: datetime
    sample_trace_id: Optional[UUID] = None
    sample_name: Optional[str] = None


class OverviewOut(BaseModel):
    total_traces: int
    total_errors: int
    error_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    total_tokens: int
    total_cost: float


class TimePoint(BaseModel):
    bucket: datetime
    calls: int
    errors: int
    avg_latency_ms: float
    tokens: int
    cost: float

class AlertRuleCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=100)
    metric_type: str
    threshold: float
    window_minutes: int = Field(default=15, ge=1, le=1440)
    webhook_url: Optional[str] = Field(default=None, max_length=500)
    webhook_format: str = "generic"
    webhook_secret: Optional[str] = Field(default=None, max_length=128)


class AlertRuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    threshold: Optional[float] = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    metric_type: str
    threshold: float
    window_minutes: int
    webhook_url: Optional[str]
    webhook_format: str
    webhook_secret: Optional[str]
    enabled: bool
    created_at: datetime


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: UUID
    rule_name: str
    metric_type: str
    value: float
    threshold: float
    message: str
    created_at: datetime

class SessionOut(BaseModel):
    session_id: str
    trace_count: int
    total_tokens: int
    total_cost: float
    avg_latency_ms: float
    last_seen: datetime


class LoginIn(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    display_name: str = Field(default="", max_length=100)
    password: str = Field(min_length=6, max_length=100)
    role: str = Field(default="member")


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=100)
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=100)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    role: str
    is_active: bool
    sso_provider: Optional[str] = None
    sso_subject: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime


class ProjectSettingsUpdate(BaseModel):
    mask_pii: Optional[bool] = None
    retention_days: Optional[int] = Field(default=None, ge=0, le=3650)



class TraceBatchIn(BaseModel):
    traces: list[TraceIn] = Field(max_length=200)


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    action: str
    target: str
    detail: Optional[Any] = None
    created_at: datetime


class ModelStatOut(BaseModel):
    model: Optional[str]
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    avg_latency_ms: float


class HistogramBucket(BaseModel):
    label: str
    count: int


class TracePageOut(BaseModel):
    items: list[TraceListItem]
    total: int
