import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, User
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
    project = Project(name=payload.name, api_key=secrets.token_hex(24))
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
    project.api_key = secrets.token_hex(24)
    db.commit()
    db.refresh(project)
    record_audit(db, admin, "project.rotate_key", project.name)
    db.commit()
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at).all()


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
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    record_audit(db, admin, "project.update", project.name, changes)
    db.commit()
    return project


