import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from sqlalchemy import func

from ..models import Project, Trace, User
from ..schemas import ProjectCreate, ProjectOut, ProjectSettingsUpdate
from ..services.audit import record_audit
from ..services.security import get_current_user, require_admin, require_member

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    member: User = Depends(require_member),
    db: Session = Depends(get_db),
):
    exists = db.query(Project).filter(Project.name == payload.name).first()
    if exists:
        return exists
    if member.role != "admin" and member.team_id is None:
        raise HTTPException(status_code=403, detail="请先创建或加入团队")
    project = Project(name=payload.name, team_id=member.team_id, api_key=secrets.token_hex(24))
    db.add(project)
    db.commit()
    db.refresh(project)
    record_audit(db, member, "project.create", project.name)
    db.commit()
    return project


@router.post("/{project_id}/rotate-key", response_model=ProjectOut)
def rotate_api_key(
    project_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """轮换项目 API Key：旧 Key 立即失效。"""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if admin.role != "admin" and project.team_id != admin.team_id:
        raise HTTPException(status_code=403, detail="无权访问其他团队的项目")
    project.api_key = secrets.token_hex(24)
    db.commit()
    db.refresh(project)
    record_audit(db, admin, "project.rotate_key", project.name)
    db.commit()
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Project)
    if user.role != "admin":
        if user.team_id is None:
            return []
        q = q.filter(Project.team_id == user.team_id)
    projects = q.order_by(Project.created_at).all()
    # 最近一次 trace 时间（前端默认选中最近活跃项目用）
    latest: dict = {}
    if projects:
        rows = (
            db.query(Trace.project_id, func.max(Trace.start_time))
            .filter(Trace.project_id.in_([p.id for p in projects]))
            .group_by(Trace.project_id)
            .all()
        )
        latest = {pid: ts for pid, ts in rows}
    return [
        ProjectOut(
            id=p.id, name=p.name, api_key=p.api_key,
            mask_pii=p.mask_pii, retention_days=p.retention_days,
            created_at=p.created_at, team_id=p.team_id,
            latest_trace_at=latest.get(p.id),
        )
        for p in projects
    ]


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectSettingsUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if admin.role != "admin" and project.team_id != admin.team_id:
        raise HTTPException(status_code=403, detail="无权访问其他团队的项目")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    record_audit(db, admin, "project.update", project.name, changes)
    db.commit()
    return project


