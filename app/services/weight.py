"""权重模块：单词重要度，基于图拓扑（六度空间/中心性），实时计算。

依据：一个单词在图里关联的节点越多，在六度空间中越核心，重要度（记忆收益）越高。
v1 用度中心性（关联边数量）近似；后续可升级为 GDS PageRank / betweenness。

两个用途：
1. 复习侧：按艾宾浩斯曲线安排复习时，优先推送高权重单词（`rank_words`）。
2. 生成侧：按「收敛强度」在权重谱上取样，决定下一轮种子单词（`select_seeds`）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import db as db_module
from app.models import graph
from app.services.memory import DEFAULT_HALF_LIFE_DAYS, memory_strength_at

# 收敛强度默认值（0.5 = 在权重谱中段取种子，既不极端收敛也不极端扩张）
DEFAULT_INTENSITY = 0.5


def compute_weights(
    gdb: db_module.GraphDB,
    category: str | None = None,
) -> list[dict]:
    """实时计算每个单词的度中心性（关联边数量）作为重要度权重。

    指定 category 时只计算该分类内的单词。
    返回按权重降序排列的 [{"text": ..., "weight": ...}, ...]。
    """
    if category:
        records = gdb.run(graph.CATEGORY_WORD_DEGREES, category=category)
    else:
        records = gdb.run(graph.ALL_WORD_DEGREES)
    return [{"text": r["text"], "weight": r["degree"]} for r in records]


def select_seeds(
    gdb: db_module.GraphDB,
    category: str | None = None,
    intensity: float = DEFAULT_INTENSITY,
    k: int = 5,
    exclude: set[str] | None = None,
) -> list[dict]:
    """按「收敛强度」在权重谱上取样，选出下一轮 autoMake 的种子单词。

    intensity ∈ [0, 1]，滑块位置：
    - 高（→1）**收敛**：取度中心性最高的核心词做种子，例句围着老词转，
      句中实词多半已在图里，新词少 → 图变密（加固既有关联）。
    - 低（→0）**扩张**：取度中心性最低的边缘词做种子，这些多半是上一轮
      刚入图、只连了一条例句的新词，让 LLM 围着它们造句能拽出大量新词 → 图长大。

    取样规则：度归一化到 0~1 后，取 |weight_norm - intensity| 最小的 k 个，
    即滑块停在权重谱哪个位置，就从哪个位置取种子（中间值取腰部词）。

    这也是自生长闭环的关键：上一轮的 `new_words` 入图后度最低，
    低强度时会自动被选成下一轮种子，无需调用方手动回灌。

    `category` 为空时在全图取样。该分类无单词（冷启动）时返回 []，
    由调用方回退到 LLM 生成种子（见 `AutoMake.pick_seeds`）。

    `exclude` 里的词不参与取样（焦点词模式下用来排除焦点词自身，避免重复），
    但仍参与归一化基准，保证「核心度」的标尺不因排除而漂移。

    返回 [{"text", "weight", "weight_norm", "distance"}, ...]，按取样优先级排序。
    """
    intensity = min(1.0, max(0.0, float(intensity)))
    skip = {w.strip().lower() for w in (exclude or set())}

    if category:
        records = gdb.run(graph.CATEGORY_WORD_DEGREES, category=category)
    else:
        records = gdb.run(graph.ALL_WORD_DEGREES)
    if not records:
        return []

    max_w = max((r["degree"] for r in records), default=0) or 1

    scored = []
    for r in records:
        if r["text"] in skip:
            continue
        w_norm = r["degree"] / max_w
        scored.append({
            "text": r["text"],
            "weight": r["degree"],
            "weight_norm": round(w_norm, 4),
            "distance": round(abs(w_norm - intensity), 4),
        })
    # 距离近的优先；同距离时偏高权重，再按字母序保证结果稳定可测
    scored.sort(key=lambda x: (x["distance"], -x["weight"], x["text"]))
    if k is None:
        return scored
    return scored[:max(0, k)]


def rank_words(
    gdb: db_module.GraphDB,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    limit: int | None = None,
    category: str | None = None,
) -> list[dict]:
    """按「重要度 × 遗忘比例」降序排列，得出推送复习的顺序。

    score = weight_norm × (1 - memory_strength)
    - 权重高 + 记忆度低（重要但忘了）→ 高分，最该先复习
    - 权重低或已记住 → 低分，靠后

    权重先归一化到 0~1（除以最大度），记忆度本就是 0~1，两者可乘。
    指定 category 时只返回该分类内的单词。

    返回 [{"text", "weight", "weight_norm", "memory_strength", "score"}, ...]。
    """
    weights = compute_weights(gdb, category=category)
    max_w = max((w["weight"] for w in weights), default=0) or 1

    now = datetime.now(timezone.utc)
    mem = {
        r["text"]: memory_strength_at(r.get("last_reviewed_at"), now, half_life_days)
        for r in gdb.run(graph.GET_WORDS_REVIEW)
    }

    # 如果指定了分类，只保留该分类内的单词
    if category:
        category_words = {w["text"] for w in weights}
    else:
        category_words = None

    scored = []
    for w in weights:
        text = w["text"]
        w_norm = w["weight"] / max_w
        m = mem.get(text, 0.0)
        scored.append({
            "text": text,
            "weight": w["weight"],
            "weight_norm": round(w_norm, 4),
            "memory_strength": round(m, 4),
            "score": round(w_norm * (1.0 - m), 4),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit] if limit else scored
