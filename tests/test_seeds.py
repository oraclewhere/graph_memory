"""收敛强度选种子的单元测试（不依赖真实 Neo4j / LLM API）。

强度语义：高 = 收敛（挑高权重核心词），低 = 扩张（挑低权重边缘词）。
"""
from __future__ import annotations

from app.config import AffixConfig
from app.models import graph
from app.models.schemas import WordInfo
from app.services.automake import AutoMake
from app.services.weight import select_seeds

from tests.test_automake import FakeLLM


class SeedGDB:
    """模拟 select_seeds 需要的度中心性查询。"""

    def __init__(self, degrees=(), all_degrees=None):
        self.degrees = list(degrees)
        self.all_degrees = list(all_degrees) if all_degrees is not None else list(degrees)
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        if query == graph.CATEGORY_WORD_DEGREES:
            return self.degrees
        if query == graph.ALL_WORD_DEGREES:
            return self.all_degrees
        return []


# 一轮 autoMake 之后的典型图形态：
# 种子词被多条例句反复用到（度高，核心），新词只挂着 1 条例句（度低，边缘）
AFTER_ONE_ROUND = [
    {"text": "government", "degree": 10},  # 种子，核心
    {"text": "promote", "degree": 5},      # 腰部
    {"text": "reform", "degree": 1},       # 上一轮新词，边缘
]


def test_high_intensity_converges_to_core_words():
    gdb = SeedGDB(AFTER_ONE_ROUND)
    picked = select_seeds(gdb, category="c", intensity=1.0, k=1)
    assert [p["text"] for p in picked] == ["government"]


def test_low_intensity_expands_from_peripheral_words():
    gdb = SeedGDB(AFTER_ONE_ROUND)
    picked = select_seeds(gdb, category="c", intensity=0.0, k=1)
    assert [p["text"] for p in picked] == ["reform"]


def test_mid_intensity_picks_waist_words():
    # 归一化后 government=1.0, promote=0.5, reform=0.1
    # 强度 0.5 时距离分别是 0.5 / 0.0 / 0.4 -> 取 promote
    gdb = SeedGDB(AFTER_ONE_ROUND)
    picked = select_seeds(gdb, category="c", intensity=0.5, k=1)
    assert [p["text"] for p in picked] == ["promote"]


def test_intensity_is_clamped_to_unit_range():
    gdb = SeedGDB(AFTER_ONE_ROUND)
    assert select_seeds(gdb, category="c", intensity=9.0, k=1)[0]["text"] == "government"
    assert select_seeds(gdb, category="c", intensity=-9.0, k=1)[0]["text"] == "reform"


def test_new_words_are_reachable_as_next_seeds():
    """自生长闭环：上一轮新词（度最低）在低强度下会被选成下一轮种子。"""
    gdb = SeedGDB(AFTER_ONE_ROUND)
    picked = [p["text"] for p in select_seeds(gdb, category="c", intensity=0.0, k=3)]
    assert picked[0] == "reform"          # 最边缘的新词排第一
    assert set(picked) == {"reform", "promote", "government"}


def test_selects_within_category_not_whole_graph():
    gdb = SeedGDB(
        degrees=[{"text": "inside", "degree": 3}],
        all_degrees=[{"text": "inside", "degree": 3}, {"text": "outside", "degree": 99}],
    )
    picked = select_seeds(gdb, category="c", intensity=1.0, k=5)
    assert [p["text"] for p in picked] == ["inside"]


def test_falls_back_to_whole_graph_without_category():
    gdb = SeedGDB(
        degrees=[{"text": "inside", "degree": 3}],
        all_degrees=[{"text": "inside", "degree": 3}, {"text": "outside", "degree": 99}],
    )
    picked = select_seeds(gdb, category=None, intensity=1.0, k=1)
    assert [p["text"] for p in picked] == ["outside"]


def test_empty_graph_returns_no_seeds():
    assert select_seeds(SeedGDB([]), category="c", intensity=0.5, k=5) == []


def test_all_isolated_words_do_not_crash():
    """所有词度为 0（max=0）时不能除零。"""
    gdb = SeedGDB([{"text": "a", "degree": 0}, {"text": "b", "degree": 0}])
    picked = select_seeds(gdb, category="c", intensity=1.0, k=2)
    assert {p["text"] for p in picked} == {"a", "b"}


def test_pick_seeds_uses_graph_when_available():
    gdb = SeedGDB(AFTER_ONE_ROUND)
    llm = FakeLLM(top_words=[WordInfo(word="from_llm")])
    am = AutoMake(gdb, llm, AffixConfig(prefixes=[], suffixes=[]))

    seeds = am.pick_seeds("c", intensity=1.0, k=1)
    assert seeds == ["government"]        # 用图里的词，没走 LLM


def test_pick_seeds_cold_starts_with_llm_on_empty_graph():
    gdb = SeedGDB([])
    llm = FakeLLM(top_words=[WordInfo(word="from_llm", definition_cn="冷启动")])
    am = AutoMake(gdb, llm, AffixConfig(prefixes=[], suffixes=[]))

    seeds = am.pick_seeds("新分类", intensity=0.5, k=3)
    assert [s.word for s in seeds] == ["from_llm"]


# --- 焦点词模式：图页面点单词上的「+」，围绕该词造句 ---


def _am(gdb):
    return AutoMake(gdb, FakeLLM(top_words=[WordInfo(word="from_llm")]),
                    AffixConfig(prefixes=[], suffixes=[]))


def test_exclude_removes_word_from_sampling():
    gdb = SeedGDB(AFTER_ONE_ROUND)
    picked = select_seeds(gdb, category="c", intensity=1.0, k=1, exclude={"government"})
    assert [p["text"] for p in picked] == ["promote"]   # 跳过被排除的核心词


def test_exclude_keeps_normalization_scale_stable():
    """排除某词不应改变归一化基准，否则「核心度」标尺会漂移。"""
    gdb = SeedGDB(AFTER_ONE_ROUND)
    picked = select_seeds(gdb, category="c", intensity=1.0, k=2, exclude={"government"})
    # 基准仍是 government 的 10，所以 promote 还是 0.5，而不是被拉成 1.0
    assert picked[0]["weight_norm"] == 0.5


def test_zero_k_selects_nothing():
    gdb = SeedGDB(AFTER_ONE_ROUND)
    assert select_seeds(gdb, category="c", intensity=0.5, k=0) == []


def test_focus_word_is_always_a_seed():
    seeds = _am(SeedGDB(AFTER_ONE_ROUND)).pick_seeds("c", intensity=1.0, k=3, focus="reform")
    assert seeds[0] == "reform"                        # 焦点词排第一且必定在
    assert "reform" not in seeds[1:]                   # 不重复出现


def test_focus_high_intensity_brings_core_companions():
    """强度高 = 例句更依赖高权重词：陪衬词取核心词。"""
    seeds = _am(SeedGDB(AFTER_ONE_ROUND)).pick_seeds("c", intensity=1.0, k=2, focus="reform")
    assert seeds == ["reform", "government"]


def test_focus_low_intensity_brings_peripheral_companions():
    """强度低 = 例句少依赖高权重词：陪衬词取边缘词。"""
    gdb = SeedGDB(AFTER_ONE_ROUND + [{"text": "edge", "degree": 1}])
    seeds = _am(gdb).pick_seeds("c", intensity=0.0, k=2, focus="reform")
    assert seeds == ["reform", "edge"]


def test_focus_alone_when_k_is_one():
    seeds = _am(SeedGDB(AFTER_ONE_ROUND)).pick_seeds("c", intensity=0.5, k=1, focus="reform")
    assert seeds == ["reform"]                         # k=1 时没有陪衬词


def test_focus_is_normalized_to_lowercase():
    seeds = _am(SeedGDB(AFTER_ONE_ROUND)).pick_seeds("c", intensity=1.0, k=1, focus="  ReForm  ")
    assert seeds == ["reform"]


def test_focus_skips_llm_cold_start_on_empty_graph():
    """图是空的但有焦点词时，焦点词本身就是合法种子，不该去调 LLM。"""
    seeds = _am(SeedGDB([])).pick_seeds("c", intensity=0.5, k=3, focus="reform")
    assert seeds == ["reform"]
