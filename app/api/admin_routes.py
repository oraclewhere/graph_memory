"""管理员 API：用户管理。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.auth import get_current_admin, get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: str


@router.get("/users", response_model=list[UserResponse])
def list_users(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """获取所有用户列表（管理员）。"""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [UserResponse(**u.to_dict()) for u in users]


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除用户（管理员）。"""
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # TODO: 同时删除用户在 Neo4j 里的数据
    db.delete(user)
    db.commit()

    return {"ok": True, "message": f"用户 {user.username} 已删除"}
