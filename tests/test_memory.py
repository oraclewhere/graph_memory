"""记忆度（艾宾浩斯曲线）与推送排序的单元测试。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import graph
from app.services.memory import memory_strength_at, review_word
from app.services.weight import rank_words

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
OLD = "2020-01-01T00:00:00+00:00"  # 很久以前 → 记忆度 ≈ 0


def test_no_review_time_returns_zero():
    assert memory_strength_at(None, now=NOW) == 0.0
    assert memory_strength_at("", now=NOW) == 0.0


def test_just_reviewed_is_full():
    assert memory_strength_at(NOW, now=NOW) == 1.0
    assert memory_strength_at(NOW.isoformat(), now=NOW) == 1.0


def test_decays_to_one_over_e_after_half_life():
    # half_life=7 天，7 天后记忆度 = e^-1 ≈ 0.3679
    last = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    val = memory_strength_at(last, now=NOW, half_life_days=7.0)
    assert abs(val - 0.36787944117144233) < 1e-6


def test_future_review_time_clamps_to_full():
    last = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    assert memory_strength_at(last, now=NOW) == 1.0


class FakeGDB:
    """模拟 rank_words 需要的两个查询。"""

    def __init__(self, degrees, reviews):
        self.degrees = degrees
        self.reviews = reviews

    def run(self, query, **params):
        if query == graph.ALL_WORD_DEGREES:
            return self.degrees
        if query == graph.GET_WORDS_REVIEW:
            return self.reviews
        return []


def test_rank_prefers_high_weight_low_memory():
    now_iso = datetime.now(timezone.utc).isoformat()
    gdb = FakeGDB(
        degrees=[{"text": "a", "degree": 10}, {"text": "b", "degree": 1}],
        reviews=[
            {"text": "a", "last_reviewed_at": OLD},      # 记忆度 ≈ 0
            {"text": "b", "last_reviewed_at": now_iso},  # 记忆度 ≈ 1
        ],
    )
    words = rank_words(gdb)
    # score = weight_norm * (1 - memory)
    # a: weight_norm=1.0, memory≈0 -> score≈1.0
    # b: weight_norm=0.1, memory≈1 -> score≈0.0
    assert [w["text"] for w in words] == ["a", "b"]
    assert words[0]["score"] > words[1]["score"]


def test_rank_low_memory_outranks_memorized_high_weight():
    now_iso = datetime.now(timezone.utc).isoformat()
    gdb = FakeGDB(
        degrees=[{"text": "a", "degree": 10}, {"text": "b", "degree": 1}],
        reviews=[
            {"text": "a", "last_reviewed_at": now_iso},  # 刚复习，记忆度高
            {"text": "b", "last_reviewed_at": OLD},       # 忘了
        ],
    )
    words = rank_words(gdb)
    # score = weight_norm * (1 - memory)
    # a: weight_norm=1.0, memory≈1 -> score≈0
    # b: weight_norm=0.1, memory≈0 -> score=0.1
    assert [w["text"] for w in words] == ["b", "a"]


class ReviewGDB:
    """模拟 review_word 的写入。"""

    def __init__(self):
        self.query = None
        self.params = None

    def run(self, query, **params):
        self.query = query
        self.params = params
        return [{
            "text": params["text"],
            "memory_strength": params["memory_strength"],
            "last_reviewed_at": params["last_reviewed_at"],
        }]


def test_review_word_resets_memory_to_full():
    gdb = ReviewGDB()
    result = review_word(gdb, "analyze")

    assert gdb.query == graph.REVIEW_WORD
    assert gdb.params["memory_strength"] == 1.0
    assert gdb.params["last_reviewed_at"] is not None
    assert result["text"] == "analyze"
    assert result["memory_strength"] == 1.0


def test_review_word_returns_none_when_word_missing():
    gdb = ReviewGDB()
    gdb.run = lambda query, **params: []
    assert review_word(gdb, "nope") is None
