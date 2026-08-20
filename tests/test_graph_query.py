"""图结构查询（get_graph）的单元测试，重点验证例句记忆度取所含词均值。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import graph
from app.services.graph_query import get_graph


class FakeGraphGDB:
    """模拟 get_graph 需要的查询（含按分类过滤的查询）。"""

    def __init__(self, categories, words, sentences, relationships,
                 word_categories=None, sentence_categories=None):
        self.categories = categories
        self.words = words
        self.sentences = sentences
        self.relationships = relationships
        self.word_categories = word_categories or {}
        self.sentence_categories = sentence_categories or {}

    def run(self, query, **params):
        if query == graph.GET_ALL_CATEGORIES:
            return [{"c": c} for c in self.categories]
        if query == graph.GET_CATEGORY_BY_NAME:
            name = params["name"]
            return [{"c": c} for c in self.categories if c.get("name") == name]
        if query == graph.GET_ALL_WORDS_FULL:
            return [{"w": w} for w in self.words]
        if query == graph.GET_CATEGORY_WORDS:
            cat = params["category"]
            return [{"w": w} for w in self.words if self.word_categories.get(w.get("text")) == cat]
        if query == graph.GET_ALL_SENTENCES:
            return [{"s": s} for s in self.sentences]
        if query == graph.GET_CATEGORY_SENTENCES:
            cat = params["category"]
            return [{"s": s} for s in self.sentences if self.sentence_categories.get(s.get("text")) == cat]
        if query == graph.GET_ALL_RELATIONSHIPS:
            return self.relationships
        return []


def test_sentence_memory_is_average_of_contained_words():
    now = datetime.now(timezone.utc).isoformat()
    gdb = FakeGraphGDB(
        categories=[],
        words=[
            {"text": "analyze", "pos": "verb", "definition_cn": "分析",
             "definition_en": "to examine", "frequency": 1,
             "memory_strength": 0.0, "last_reviewed_at": now},   # 刚复习 → 记忆度 ≈ 1
            {"text": "data", "pos": "noun", "definition_cn": "数据",
             "definition_en": "facts", "frequency": 1,
             "memory_strength": 0.0, "last_reviewed_at": None},   # 未复习 → 记忆度 0
        ],
        sentences=[{"text": "analyze the data", "translation": "分析数据"}],
        relationships=[
            {"a_label": "Sentence", "a_key": "analyze the data", "b_label": "Word", "b_key": "analyze", "type": "CONTAINS"},
            {"a_label": "Sentence", "a_key": "analyze the data", "b_label": "Word", "b_key": "data", "type": "CONTAINS"},
        ],
    )

    result = get_graph(gdb)
    sent = [n for n in result["nodes"] if n["label"] == "Sentence"][0]
    # (1.0 + 0.0) / 2 = 0.5
    assert abs(sent["properties"]["memory_strength"] - 0.5) < 0.01


def test_sentence_without_words_has_zero_memory():
    gdb = FakeGraphGDB(
        categories=[],
        words=[],
        sentences=[{"text": "orphan sentence", "translation": "无关联"}],
        relationships=[],
    )
    result = get_graph(gdb)
    sent = [n for n in result["nodes"] if n["label"] == "Sentence"][0]
    assert sent["properties"]["memory_strength"] == 0.0


def test_sentence_includes_contained_words():
    gdb = FakeGraphGDB(
        categories=[],
        words=[],
        sentences=[{"text": "analyze the data", "translation": "分析数据"}],
        relationships=[
            {"a_label": "Sentence", "a_key": "analyze the data", "b_label": "Word", "b_key": "data", "type": "CONTAINS"},
            {"a_label": "Sentence", "a_key": "analyze the data", "b_label": "Word", "b_key": "analyze", "type": "CONTAINS"},
        ],
    )
    result = get_graph(gdb)
    sent = [n for n in result["nodes"] if n["label"] == "Sentence"][0]
    assert sent["properties"]["words"] == ["analyze", "data"]


def test_category_subgraph_filters_nodes_and_edges():
    gdb = FakeGraphGDB(
        categories=[
            {"name": "tech", "description": "科技"},
            {"name": "food", "description": "食物"},
        ],
        words=[
            {"text": "data", "pos": "noun", "definition_cn": "数据",
             "definition_en": "facts", "frequency": 1,
             "memory_strength": 0.0, "last_reviewed_at": None},
            {"text": "apple", "pos": "noun", "definition_cn": "苹果",
             "definition_en": "a fruit", "frequency": 1,
             "memory_strength": 0.0, "last_reviewed_at": None},
        ],
        sentences=[
            {"text": "analyze the data", "translation": "分析数据"},
            {"text": "eat an apple", "translation": "吃苹果"},
        ],
        relationships=[
            {"a_label": "Word", "a_key": "data", "b_label": "Category", "b_key": "tech", "type": "BELONGS_TO"},
            {"a_label": "Sentence", "a_key": "analyze the data", "b_label": "Category", "b_key": "tech", "type": "BELONGS_TO"},
            {"a_label": "Sentence", "a_key": "analyze the data", "b_label": "Word", "b_key": "data", "type": "CONTAINS"},
            {"a_label": "Word", "a_key": "apple", "b_label": "Category", "b_key": "food", "type": "BELONGS_TO"},
            {"a_label": "Sentence", "a_key": "eat an apple", "b_label": "Category", "b_key": "food", "type": "BELONGS_TO"},
            {"a_label": "Sentence", "a_key": "eat an apple", "b_label": "Word", "b_key": "apple", "type": "CONTAINS"},
        ],
        word_categories={"data": "tech", "apple": "food"},
        sentence_categories={"analyze the data": "tech", "eat an apple": "food"},
    )

    result = get_graph(gdb, category="tech")
    node_ids = {n["id"] for n in result["nodes"]}

    assert "word:data" in node_ids
    assert "word:apple" not in node_ids
    assert "sentence:analyze the data" in node_ids
    assert "sentence:eat an apple" not in node_ids
    assert "category:tech" in node_ids
    assert "category:food" not in node_ids
    # 所有边两端都在子图内
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in result["edges"])
    # CONTAINS 边保留
    assert any(e["type"] == "CONTAINS" for e in result["edges"])
