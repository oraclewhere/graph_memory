"""autoMake 核心循环的单元测试（不依赖真实 Neo4j / LLM API）。"""
from __future__ import annotations

from app.config import AffixConfig
from app.models import graph
from app.models.schemas import SentenceInfo, WordInfo
from app.services.automake import AutoMake
from app.services.llm import LLMClient


class FakeGraphDB:
    """内存模拟 Neo4j，精确匹配 graph 查询常量并记录调用。"""

    def __init__(self, words=()):
        self.words = set(words)
        self.categories = set()
        self.sentences = []
        self.contains_edges = []  # (sentence, word)
        self.prefix_edges = []  # (a, b, affix)
        self.suffix_edges = []  # (a, b, affix)
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        if query == graph.GET_ALL_WORDS:
            return [{"text": w} for w in sorted(self.words)]
        if query == graph.WORDS_WITH_PREFIX:
            p = params["prefix"]
            return [{"text": w} for w in sorted(self.words) if w.startswith(p)]
        if query == graph.WORDS_WITH_SUFFIX:
            s = params["suffix"]
            return [{"text": w} for w in sorted(self.words) if w.endswith(s)]
        if query == graph.MERGE_WORD:
            self.words.add(params["text"])
        elif query == graph.MERGE_CATEGORY:
            self.categories.add(params["name"])
        elif query == graph.MERGE_SENTENCE:
            self.sentences.append(params["text"])
        elif query == graph.LINK_SENTENCE_WORD:
            self.contains_edges.append((params["text"], params["word"]))
        elif query == graph.LINK_SHARES_PREFIX:
            self.prefix_edges.append((params["a"], params["b"], params["affix"]))
        elif query == graph.LINK_SHARES_SUFFIX:
            self.suffix_edges.append((params["a"], params["b"], params["affix"]))
        return []


class FakeLLM:
    """返回固定结构化结果的假 LLM 客户端。"""

    def __init__(self, sentences=(), top_words=()):
        self.sentences = list(sentences)  # list[SentenceInfo]
        self.top_words = list(top_words)  # list[WordInfo]

    def generate_sentences(self, seeds, category, n):
        return self.sentences

    def generate_top_words(self, requirement, n):
        return self.top_words

    def generate_definitions(self, words):
        return [WordInfo(word=w) for w in words]


def test_parse_json():
    assert LLMClient._parse_json('["a", "b"]') == ["a", "b"]
    assert LLMClient._parse_json('```json\n[{"word": "x"}]\n```') == [{"word": "x"}]
    assert LLMClient._parse_json("not valid json") is None


def test_to_word_infos():
    infos = LLMClient._to_word_infos([
        {"word": "assert", "pos": "verb", "definition_cn": "断言", "definition_en": "to state"},
    ])
    assert infos[0].word == "assert"
    assert infos[0].pos == "verb"
    assert infos[0].definition_cn == "断言"
    assert infos[0].definition_en == "to state"


def test_run_extracts_new_words():
    gdb = FakeGraphDB()
    si = SentenceInfo(
        sentence="The government promotes education reform.",
        translation="政府推动教育改革。",
        words=[
            WordInfo(word="government", pos="noun", definition_cn="政府", definition_en="governing body"),
            WordInfo(word="promote", pos="verb", definition_cn="推动", definition_en="to help develop"),
            WordInfo(word="education", pos="noun", definition_cn="教育", definition_en="teaching"),
            WordInfo(word="reform", pos="noun", definition_cn="改革", definition_en="improvement"),
        ],
    )
    llm = FakeLLM(sentences=[si])
    affixes = AffixConfig(prefixes=[], suffixes=[])
    result = AutoMake(gdb, llm, affixes).run(
        category="考研英语", seeds=["government"], n=1
    )

    assert "government" in gdb.words  # 种子入图
    assert "promote" in result["new_words"]
    assert "education" in result["new_words"]
    assert "reform" in result["new_words"]
    assert result["category"] == "考研英语"


def test_seed_word_links_to_sentence_via_lemma():
    """词形还原核心：LLM 返回原形 assert，与种子 assert 匹配，不重复建节点且 CONTAINS 正确关联。"""
    gdb = FakeGraphDB()
    si = SentenceInfo(
        sentence="He asserts the fact.",
        translation="他断言了这个事实。",
        words=[WordInfo(word="assert", pos="verb", definition_cn="断言", definition_en="to state")],
    )
    llm = FakeLLM(sentences=[si])
    affixes = AffixConfig(prefixes=[], suffixes=[])
    result = AutoMake(gdb, llm, affixes).run(category="c", seeds=["assert"], n=1)

    assert "assert" in gdb.words          # 种子 assert 在图
    assert result["new_words"] == []      # 原形匹配，不重复入图
    assert ("He asserts the fact.", "assert") in gdb.contains_edges  # 正确关联例句


def test_run_builds_prefix_edges():
    gdb = FakeGraphDB(words=["unhappy"])
    si = SentenceInfo(
        sentence="Unable to adapt.",
        translation="无法适应。",
        words=[WordInfo(word="unable", pos="adj", definition_cn="无法的", definition_en="not able")],
    )
    llm = FakeLLM(sentences=[si])
    affixes = AffixConfig(prefixes=["un"], suffixes=[])
    AutoMake(gdb, llm, affixes).run(category="c", seeds=[], n=1)

    pairs = {(a, b) for a, b, _ in gdb.prefix_edges}
    assert ("unable", "unhappy") in pairs or ("unhappy", "unable") in pairs


def test_run_builds_suffix_edges():
    gdb = FakeGraphDB(words=["education"])
    si = SentenceInfo(
        sentence="The nation builds a station.",
        translation="这个国家建了一个车站。",
        words=[
            WordInfo(word="nation", pos="noun", definition_cn="国家", definition_en="a country"),
            WordInfo(word="station", pos="noun", definition_cn="车站", definition_en="a stopping place"),
        ],
    )
    llm = FakeLLM(sentences=[si])
    affixes = AffixConfig(prefixes=[], suffixes=["tion"])
    AutoMake(gdb, llm, affixes).run(category="c", seeds=[], n=1)

    affixed = {a for a, _, _ in gdb.suffix_edges} | {b for _, b, _ in gdb.suffix_edges}
    assert "education" in affixed
