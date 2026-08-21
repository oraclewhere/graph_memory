"""图结构查询：把 Neo4j 里的图导出为前端可视化友好的「节点 + 边」结构。"""
from __future__ import annotations

from datetime import datetime, timezone

from app import db as db_module
from app.config import AffixConfig, load_affix_config
from app.models import graph
from app.services.memory import DEFAULT_HALF_LIFE_DAYS, memory_strength_at


def get_graph(
    gdb: db_module.GraphDB,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    category: str | None = None,
    affixes: AffixConfig | None = None,
    user_id: int | None = None,
) -> dict:
    """导出图结构：{"nodes": [...], "edges": [...]}。

    - node: {"id", "label", "properties"}
    - edge: {"source", "target", "type"}
    - id 格式：word:<text> / category:<name> / sentence:<text>

    记忆度：Word 按艾宾浩斯曲线实时计算；Sentence 取所含 Word 的记忆度均值。
    权重：Word 取度中心性（与 `weight.py` 同源，全图口径）；Sentence 取所含词数。
    前端用它做「按权重/记忆度同心圆布局」——值越大越靠近圆心。
    category 指定时只导出该分类的子图（其 Word/Sentence/Category 及内部边）。
    """
    now = datetime.now(timezone.utc)
    nodes: list[dict] = []
    edges: list[dict] = []

    # 度中心性，与 weight.compute_weights 同一个查询，保证前端排布和推送排序口径一致
    degrees = {r["text"]: r["degree"] for r in gdb.run(graph.ALL_WORD_DEGREES, user_id=user_id)}

    # Word：先算记忆度，并记录 text -> memory 供例句均值使用
    words_query = graph.GET_CATEGORY_WORDS if category else graph.GET_ALL_WORDS_FULL
    word_params = {"category": category, "user_id": user_id} if category else {"user_id": user_id}
    word_mem: dict[str, float] = {}
    for r in gdb.run(words_query, **word_params):
        w = dict(r["w"])
        text = w.get("text", "")
        mem = memory_strength_at(w.get("last_reviewed_at"), now, half_life_days)
        word_mem[text] = mem
        nodes.append({
            "id": f"word:{text}",
            "label": "Word",
            "properties": {
                "text": text,
                "pos": w.get("pos", ""),
                "definition_cn": w.get("definition_cn", ""),
                "definition_en": w.get("definition_en", ""),
                "frequency": w.get("frequency", 0),
                "memory_strength": round(mem, 4),
                "weight": degrees.get(text, 0),
            },
        })

    # Category
    cats_query = graph.GET_CATEGORY_BY_NAME if category else graph.GET_ALL_CATEGORIES
    cat_params = {"name": category, "user_id": user_id} if category else {"user_id": user_id}
    for r in gdb.run(cats_query, **cat_params):
        c = dict(r["c"])
        nodes.append({
            "id": f"category:{c.get('name', '')}",
            "label": "Category",
            "properties": {
                "name": c.get("name", ""),
                "description": c.get("description", ""),
            },
        })

    # Sentence：先占位，记忆度稍后按所含词均值填入
    sents_query = graph.GET_CATEGORY_SENTENCES if category else graph.GET_ALL_SENTENCES
    sent_params = {"category": category, "user_id": user_id} if category else {"user_id": user_id}
    sentence_nodes: list[dict] = []
    for r in gdb.run(sents_query, **sent_params):
        s = dict(r["s"])
        sentence_nodes.append({
            "id": f"sentence:{s.get('text', '')}",
            "label": "Sentence",
            "properties": {
                "text": s.get("text", ""),
                "translation": s.get("translation", ""),
                "memory_strength": 0.0,
            },
        })

    # 边 + 统计每个例句所含单词的记忆度之和/个数，并收集所含单词原形
    # 子图模式：只保留两端都在子图内的边
    node_ids: set[str] | None = None
    if category:
        node_ids = {n["id"] for n in nodes}
        node_ids.update(sn["id"] for sn in sentence_nodes)
    sent_sum: dict[str, tuple[float, int]] = {}
    sent_words: dict[str, set[str]] = {}

    # 加载词缀配置（用于边上显示词缀含义）
    if affixes is None:
        affixes = load_affix_config()

    for r in gdb.run(graph.GET_ALL_RELATIONSHIPS, user_id=user_id):
        source = f"{str(r['a_label']).lower()}:{r['a_key']}"
        target = f"{str(r['b_label']).lower()}:{r['b_key']}"
        if node_ids is not None and (source not in node_ids or target not in node_ids):
            continue

        edge_data = {
            "source": source,
            "target": target,
            "type": r["type"],
        }

        # 对于词缀边，查找词缀含义并构造 display_label
        affix = r.get("affix")
        if affix and r["type"] in ("SHARES_PREFIX", "SHARES_SUFFIX"):
            if r["type"] == "SHARES_PREFIX":
                info = affixes.get_prefix_meaning(affix)
                suffix_char = "-"  # 前缀显示为 "un-"
            else:
                info = affixes.get_suffix_meaning(affix)
                suffix_char = "-"  # 后缀显示为 "-tion"

            if info:
                meaning_cn = info.meaning_cn
                # 构造显示标签：前缀 "un-" 或后缀 "-tion"，带中文含义
                if r["type"] == "SHARES_PREFIX":
                    display_label = f"{affix}-{meaning_cn}" if meaning_cn else affix
                else:
                    display_label = f"-{affix} {meaning_cn}" if meaning_cn else affix
            else:
                display_label = affix

            edge_data["affix"] = affix
            edge_data["meaning_cn"] = meaning_cn if info else ""
            edge_data["meaning_en"] = info.meaning_en if info else ""
            edge_data["display_label"] = display_label

        edges.append(edge_data)

        if r["type"] == "CONTAINS":
            sent_text = r["a_key"]  # Sentence 的 text
            word_text = r["b_key"]  # Word 的 text
            s, c = sent_sum.get(sent_text, (0.0, 0))
            sent_sum[sent_text] = (s + word_mem.get(word_text, 0.0), c + 1)
            sent_words.setdefault(sent_text, set()).add(word_text)

    # 填例句平均记忆度 + 所含单词（供前端在例句内点击单词跳转）
    for sn in sentence_nodes:
        text = sn["properties"]["text"]
        s, c = sent_sum.get(text, (0.0, 0))
        avg = (s / c) if c else 0.0
        sn["properties"]["memory_strength"] = round(avg, 4)
        sn["properties"]["words"] = sorted(sent_words.get(text, []))
        sn["properties"]["weight"] = c          # 例句权重 = 所含实词数
        nodes.append(sn)

    return {"nodes": nodes, "edges": edges}
