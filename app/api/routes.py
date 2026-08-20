"""FastAPI 路由。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import db as db_module
from app.config import load_affix_config
from app.models import graph
from app.models.schemas import WordInfo
from app.services import graph_query, memory
from app.services.automake import AutoMake
from app.services.llm import LLMClient
from app.services.weight import DEFAULT_INTENSITY, rank_words, select_seeds

router = APIRouter(prefix="/api")


class ReviewRequest(BaseModel):
    word: str


class CandidateRequest(BaseModel):
    category: str
    n: int = 10


class AutoMakeRequest(BaseModel):
    category: str
    seeds: list[WordInfo] = Field(default_factory=list)
    n_sentences: int = 10
    description: str = ""
    # 收敛强度：seeds 为空时按此强度从图里自动选种子（高=收敛，低=扩张）
    intensity: float = DEFAULT_INTENSITY
    n_seeds: int = 5
    # 焦点词：非空则该词必定作为种子，其余按强度取样当陪衬（图页面点单词的「+」）
    focus_word: str = ""


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/graph")
def graph_structure(category: str | None = None) -> dict:
    """返回图结构（节点 + 边）；指定 category 时只返回该分类的子图。"""
    gdb = db_module.GraphDB()
    try:
        return graph_query.get_graph(gdb, category=category)
    finally:
        gdb.close()


@router.get("/categories")
def categories() -> dict:
    """返回所有分类及统计（笔记列表用）。"""
    gdb = db_module.GraphDB()
    try:
        rows = gdb.run(graph.GET_CATEGORY_STATS)
        return {
            "categories": [
                {
                    "name": r["name"],
                    "description": r.get("description") or "",
                    "word_count": r.get("word_count", 0),
                    "sentence_count": r.get("sentence_count", 0),
                }
                for r in rows
            ]
        }
    finally:
        gdb.close()


@router.post("/candidate-words")
def candidate_words(req: CandidateRequest) -> dict:
    """让 LLM 生成该分类的候选种子单词（只调 LLM、不写库，供半自动勾选）。"""
    llm = LLMClient()
    words = llm.generate_top_words(req.category, req.n)
    return {"words": [w.model_dump() for w in words]}


@router.get("/seeds")
def seeds(
    category: str,
    intensity: float = DEFAULT_INTENSITY,
    k: int = 5,
    focus: str = "",
) -> dict:
    """预览按收敛强度选出的种子单词（只读图、不调 LLM、不写库）。

    供前端滑块即时反馈：拖动强度就能看到这一轮会拿哪些词当种子。
    `focus` 非空 = 焦点词模式，返回的是**陪衬词**（焦点词自身由前端展示，
    已从取样中排除），此时不存在冷启动。分类还没入图时返回空列表。
    """
    gdb = db_module.GraphDB()
    try:
        focus_word = focus.strip().lower()
        if focus_word:
            picked = select_seeds(
                gdb,
                category=category,
                intensity=intensity,
                k=max(0, k - 1),
                exclude={focus_word},
            )
            return {"words": picked, "intensity": intensity,
                    "focus": focus_word, "cold_start": False}
        picked = select_seeds(gdb, category=category, intensity=intensity, k=k)
        return {"words": picked, "intensity": intensity,
                "focus": "", "cold_start": not picked}
    finally:
        gdb.close()


@router.post("/automake")
def automake(req: AutoMakeRequest) -> dict:
    """执行一轮 autoMake 并写库。

    `seeds` 非空 = 用勾选的种子（半自动，首页新建笔记用）；
    `seeds` 为空 = 按 `intensity` 收敛强度从图里自动选种子（图页面「+」）；
    再带上 `focus_word` = 焦点词模式（图页面点单词的「+」），该词必定入种子。
    图里该分类还没词且无焦点词时，回退 LLM 冷启动。
    """
    gdb = db_module.GraphDB()
    try:
        gdb.init_constraints()
        affixes = load_affix_config()
        llm = LLMClient()
        am = AutoMake(gdb, llm, affixes)
        auto = not req.seeds
        seed_list = (
            am.pick_seeds(
                req.category,
                intensity=req.intensity,
                k=req.n_seeds,
                focus=req.focus_word,
            )
            if auto
            else req.seeds
        )
        result = am.run(
            category=req.category,
            seeds=seed_list,
            n=req.n_sentences,
            description=req.description,
        )
        return {
            "ok": True,
            "auto_seeds": auto,
            "intensity": req.intensity,
            "focus_word": req.focus_word if auto else "",
            **result,
        }
    finally:
        gdb.close()


@router.get("/rank")
def rank(limit: int | None = None) -> dict:
    """按「权重归一化 × (1 - 记忆度)」降序返回推送复习顺序。"""
    gdb = db_module.GraphDB()
    try:
        return {"words": rank_words(gdb, limit=limit)}
    finally:
        gdb.close()


@router.post("/review")
def review(req: ReviewRequest) -> dict:
    """复习成功：重置该词记忆度，返回更新后的词 + 下一个待复习词（rank 第一位）。"""
    gdb = db_module.GraphDB()
    try:
        updated = memory.review_word(gdb, req.word)
        next_words = rank_words(gdb, limit=1)
        return {
            "ok": updated is not None,
            "word": req.word,
            "memory_strength": updated["memory_strength"] if updated else None,
            "next": next_words[0] if next_words else None,
        }
    finally:
        gdb.close()
