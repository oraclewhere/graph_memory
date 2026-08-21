"""Neo4j 图结构常量与 Cypher 查询。

数据隔离：所有节点都带 user_id 属性，所有查询都按 user_id 过滤。
"""
from __future__ import annotations

# 节点标签
CATEGORY = "Category"
WORD = "Word"
SENTENCE = "Sentence"

# 关系类型
BELONGS_TO = "BELONGS_TO"
CONTAINS = "CONTAINS"
SHARES_PREFIX = "SHARES_PREFIX"
SHARES_SUFFIX = "SHARES_SUFFIX"

# --- Cypher 查询（单行字符串，便于测试中精确匹配）---
# 所有查询都带 user_id 参数，实现数据隔离

# 分类：按 (name, user_id) 唯一
MERGE_CATEGORY = (
    "MERGE (c:Category {name: $name, user_id: $user_id}) "
    "ON CREATE SET c.description = $description RETURN c"
)

# 单词：按 (text, user_id) 唯一
MERGE_WORD = (
    "MERGE (w:Word {text: $text, user_id: $user_id}) ON CREATE SET w.pos = $pos, w.frequency = 0, "
    "w.definition_cn = $definition_cn, w.definition_en = $definition_en, "
    "w.memory_strength = 0.0 RETURN w"
)

LINK_WORD_CATEGORY = (
    "MATCH (w:Word {text: $text, user_id: $user_id}) "
    "MATCH (c:Category {name: $category, user_id: $user_id}) "
    "MERGE (w)-[:BELONGS_TO]->(c)"
)

# 例句：按 (text, user_id) 唯一
MERGE_SENTENCE = (
    "MERGE (s:Sentence {text: $text, user_id: $user_id}) ON CREATE SET s.created_at = $created_at, "
    "s.translation = $translation RETURN s"
)

LINK_SENTENCE_CATEGORY = (
    "MATCH (s:Sentence {text: $text, user_id: $user_id}) "
    "MATCH (c:Category {name: $category, user_id: $user_id}) "
    "MERGE (s)-[:BELONGS_TO]->(c)"
)

LINK_SENTENCE_WORD = (
    "MATCH (s:Sentence {text: $text, user_id: $user_id}) "
    "MATCH (w:Word {text: $word, user_id: $user_id}) "
    "MERGE (s)-[r:CONTAINS]->(w) ON CREATE SET w.frequency = w.frequency + 1"
)

LINK_SHARES_PREFIX = (
    "MATCH (a:Word {text: $a, user_id: $user_id}) "
    "MATCH (b:Word {text: $b, user_id: $user_id}) "
    "MERGE (a)-[:SHARES_PREFIX {affix: $affix}]->(b)"
)

LINK_SHARES_SUFFIX = (
    "MATCH (a:Word {text: $a, user_id: $user_id}) "
    "MATCH (b:Word {text: $b, user_id: $user_id}) "
    "MERGE (a)-[:SHARES_SUFFIX {affix: $affix}]->(b)"
)

GET_ALL_WORDS = "MATCH (w:Word {user_id: $user_id}) RETURN w.text AS text"

WORDS_WITH_PREFIX = (
    "MATCH (w:Word {user_id: $user_id}) WHERE w.text STARTS WITH $prefix RETURN w.text AS text"
)

WORDS_WITH_SUFFIX = (
    "MATCH (w:Word {user_id: $user_id}) WHERE w.text ENDS WITH $suffix RETURN w.text AS text"
)

# 度中心性：统计每个单词的关联边数量（权重模块 v1 实时计算用）
ALL_WORD_DEGREES = (
    "MATCH (w:Word {user_id: $user_id}) OPTIONAL MATCH (w)-[r]-() "
    "RETURN w.text AS text, count(r) AS degree ORDER BY degree DESC"
)

# 分类内的度中心性（按收敛强度选种子用，只在该分类子图里取样）
CATEGORY_WORD_DEGREES = (
    "MATCH (w:Word {user_id: $user_id})-[:BELONGS_TO]->(c:Category {name: $category, user_id: $user_id}) "
    "OPTIONAL MATCH (w)-[r]-() "
    "RETURN w.text AS text, count(r) AS degree ORDER BY degree DESC"
)

# --- 图结构导出（查询接口用）---

GET_ALL_CATEGORIES = "MATCH (c:Category {user_id: $user_id}) RETURN c"

GET_ALL_WORDS_FULL = "MATCH (w:Word {user_id: $user_id}) RETURN w"

GET_ALL_SENTENCES = "MATCH (s:Sentence {user_id: $user_id}) RETURN s"

# 所有边：a_label/a_key 标识起点（Word/Sentence 用 text，Category 用 name）
# 新增：返回 r.affix 属性（SHARES_PREFIX/SHARES_SUFFIX 边有该属性）
# 只返回属于当前用户的边
GET_ALL_RELATIONSHIPS = (
    "MATCH (a {user_id: $user_id})-[r]->(b {user_id: $user_id}) "
    "RETURN labels(a)[0] AS a_label, coalesce(a.text, a.name) AS a_key, "
    "labels(b)[0] AS b_label, coalesce(b.text, b.name) AS b_key, type(r) AS type, "
    "r.affix AS affix"
)

# 记忆度计算需要的时间锚点
GET_WORDS_REVIEW = (
    "MATCH (w:Word {user_id: $user_id}) RETURN w.text AS text, w.last_reviewed_at AS last_reviewed_at"
)

# 复习成功：重置记忆度 + 刷新时间锚点（由复习/反刍模块触发）
REVIEW_WORD = (
    "MATCH (w:Word {text: $text, user_id: $user_id}) "
    "SET w.memory_strength = $memory_strength, w.last_reviewed_at = $last_reviewed_at "
    "RETURN w.text AS text, w.memory_strength AS memory_strength, "
    "w.last_reviewed_at AS last_reviewed_at"
)

# --- 分类维度查询（笔记列表 / 子图过滤用）---

GET_CATEGORY_BY_NAME = "MATCH (c:Category {name: $name, user_id: $user_id}) RETURN c"

GET_CATEGORY_WORDS = (
    "MATCH (w:Word {user_id: $user_id})-[:BELONGS_TO]->(c:Category {name: $category, user_id: $user_id}) RETURN w"
)

GET_CATEGORY_SENTENCES = (
    "MATCH (s:Sentence {user_id: $user_id})-[:BELONGS_TO]->(c:Category {name: $category, user_id: $user_id}) RETURN s"
)

GET_CATEGORY_STATS = (
    "MATCH (c:Category {user_id: $user_id}) "
    "OPTIONAL MATCH (w:Word {user_id: $user_id})-[:BELONGS_TO]->(c) "
    "OPTIONAL MATCH (s:Sentence {user_id: $user_id})-[:BELONGS_TO]->(c) "
    "RETURN c.name AS name, c.description AS description, "
    "count(DISTINCT w) AS word_count, count(DISTINCT s) AS sentence_count "
    "ORDER BY name"
)
