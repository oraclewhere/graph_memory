"""用户个人信息 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.auth import get_current_user, get_db

router = APIRouter(prefix="/api/user", tags=["user"])


class ProfileUpdateRequest(BaseModel):
    """更新用户信息请求。"""
    llm_api_base: str = Field(default="", description="LLM API base URL")
    llm_api_key: str = Field(default="", description="LLM API key")
    llm_model: str = Field(default="", description="LLM model name")
    memory_base_ms: int = Field(default=1500, description="记忆模式卡片揭示基础时间（毫秒）")
    memory_per_letter_ms: int = Field(default=200, description="记忆模式每字母增量时间（毫秒）")


@router.get("/profile")
def get_profile(
    user: User = Depends(get_current_user),
) -> dict:
    """获取用户个人信息（包括 LLM 配置）。"""
    return {
        "ok": True,
        "user": user.to_dict(),
    }


@router.put("/profile")
def update_profile(
    req: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """更新用户 LLM 配置和记忆模式动画配置。"""
    # 更新用户配置（空字符串表示清空，使用全局配置）
    user.llm_api_base = req.llm_api_base or None
    user.llm_api_key = req.llm_api_key or None
    user.llm_model = req.llm_model or None
    # 记忆模式动画配置
    user.memory_base_ms = max(500, min(3000, req.memory_base_ms))
    user.memory_per_letter_ms = max(50, min(500, req.memory_per_letter_ms))

    db.add(user)
    db.commit()
    db.refresh(user)

    return {
        "ok": True,
        "user": user.to_dict(),
        "message": "配置已保存",
    }
