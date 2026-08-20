"""记忆度模块：根据艾宾浩斯遗忘曲线计算单词当前的记忆程度。

艾宾浩斯遗忘曲线：记忆保留率随时间指数衰减。

    R = e^(-Δt / half_life)

- Δt        = 距上次学习/复习的天数
- half_life = 记忆半衰期（记忆衰减到一半所需的天数），默认 7 天

记忆度 memory_strength ∈ (0, 1]：
- 刚学习/复习时为 1.0（完全记住）
- 随时间衰减，复习后重置为 1.0（由反刍/复习模块显式触发）
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app import db as db_module
from app.models import graph

DEFAULT_HALF_LIFE_DAYS = 7.0


def memory_strength_at(
    last_reviewed_at: str | datetime | None,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """根据上次复习时间计算当前记忆度（艾宾浩斯曲线）。

    若没有复习时间（旧数据 / 未知），保守返回 0.0（视为未记忆，优先被推送复习）。
    """
    if not last_reviewed_at:
        return 0.0
    if isinstance(last_reviewed_at, str):
        try:
            last = datetime.fromisoformat(last_reviewed_at)
        except ValueError:
            return 0.0
    else:
        last = last_reviewed_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta_days = max(0.0, (now - last).total_seconds() / 86400.0)
    return math.exp(-delta_days / half_life_days)


def review_word(
    gdb: db_module.GraphDB,
    text: str,
    memory_strength: float = 1.0,
) -> dict | None:
    """复习成功：把记忆度重置为给定值（默认 1.0），并把 last_reviewed_at 刷新为现在。

    返回更新后的 {"text", "memory_strength", "last_reviewed_at"}，词不存在时返回 None。
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = gdb.run(
        graph.REVIEW_WORD,
        text=text,
        memory_strength=memory_strength,
        last_reviewed_at=now,
    )
    return rows[0] if rows else None
