from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project


def get_project(x_api_key: str = Header(alias="X-API-Key"), db: Session = Depends(get_db)) -> Project:
    project = db.query(Project).filter(Project.api_key == x_api_key).first()
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return project
