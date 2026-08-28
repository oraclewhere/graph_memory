"""用户模型（MySQL）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class User(Base):
    """用户表。"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum("user", "admin", name="user_role"), default="user", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 用户自定义 LLM 配置（可选，为空时使用全局配置）
    llm_api_base = Column(String(500), nullable=True)
    llm_api_key = Column(String(500), nullable=True)
    llm_model = Column(String(100), nullable=True)

    # 记忆模式动画配置
    memory_base_ms = Column(Integer, default=1500, nullable=True)
    memory_per_letter_ms = Column(Integer, default=200, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "llm_api_base": self.llm_api_base or "",
            "llm_api_key": self.llm_api_key or "",
            "llm_model": self.llm_model or "",
            "memory_base_ms": self.memory_base_ms if self.memory_base_ms is not None else 1500,
            "memory_per_letter_ms": self.memory_per_letter_ms if self.memory_per_letter_ms is not None else 200,
        }
