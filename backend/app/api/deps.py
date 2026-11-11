from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project
from ..services.security import get_current_user


def get_project(x_api_key: str = Header(alias="X-API-Key"), db: Session = Depends(get_db)) -> Project:
    project = db.query(Project).filter(Project.api_key == x_api_key).first()
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return project


def team_projects(user = Depends(get_current_user), db: Session = Depends(get_db)):
    """当前用户可见的项目 id 集合。None=全部（平台管理员）；[]=无团队（看不到任何数据）。"""
    from ..models import Project
    if user.role == "admin":
        return None
    if user.team_id is None:
        return []
    return [row[0] for row in db.query(Project.id).filter(Project.team_id == user.team_id).all()]
