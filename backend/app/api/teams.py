"""团队：登录后可创建自己的团队（生成邀请码接入应用），或凭邀请码加入他人团队。"""
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Team, User
from ..schemas import TeamCreate, TeamJoinIn
from ..services.security import get_current_user

router = APIRouter(prefix="/api/team", tags=["team"])


def _team_of(user: User, db: Session) -> Team | None:
    return db.get(Team, user.team_id) if user.team_id else None


class TeamOut(BaseModel):
    name: str
    invite_code: str | None = None   # 仅团队创建者可见
    is_owner: bool = False
    members: int = 0


@router.get("")
def my_team(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    team = _team_of(user, db)
    if team is None:
        return None
    members = db.query(User).filter(User.team_id == team.id).count()
    is_owner = team.created_by == user.id
    return TeamOut(name=team.name, invite_code=team.invite_code if is_owner else None,
                   is_owner=is_owner, members=members)


@router.post("", status_code=201)
def create_team(payload: TeamCreate, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """创建团队：创建者自动加入，获得邀请码（可让同事凭码加入/接入应用）。"""
    if user.team_id:
        raise HTTPException(status_code=409, detail="你已加入团队，退出后才能创建新团队")
    team = Team(name=payload.name.strip()[:100], invite_code=secrets.token_hex(4), created_by=user.id)
    db.add(team)
    db.flush()
    user.team_id = team.id
    if user.role == "viewer":
        user.role = "member"  # 团队创建者需要能建项目/告警接入自己的应用
    db.commit()
    return {"name": team.name, "invite_code": team.invite_code, "is_owner": True}


@router.post("/join")
def join_team(payload: TeamJoinIn, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    if user.team_id:
        raise HTTPException(status_code=409, detail="你已加入团队")
    team = db.query(Team).filter(Team.invite_code == payload.invite_code.strip()).first()
    if team is None:
        raise HTTPException(status_code=404, detail="邀请码无效")
    user.team_id = team.id
    db.commit()
    return {"name": team.name}


@router.post("/invite-code")
def regenerate_invite_code(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """重新生成邀请码：旧码立即失效（团队创建者可操作）。"""
    team = _team_of(user, db)
    if team is None:
        raise HTTPException(status_code=404, detail="你还没有加入团队")
    if team.created_by != user.id:
        raise HTTPException(status_code=403, detail="仅团队创建者可操作")
    team.invite_code = secrets.token_hex(4)
    db.commit()
    return {"invite_code": team.invite_code}
