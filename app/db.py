"""Neo4j 连接与约束初始化。"""
from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase

# 与 docker-compose.yml 起的本地 Neo4j 对应
DEFAULT_URI = "bolt://localhost:7687"
DEFAULT_USER = "neo4j"
DEFAULT_PASSWORD = "password"


class GraphDB:
    """Neo4j 图数据库封装。所有查询统一走 run()，返回 list[dict]。"""

    def __init__(
        self,
        uri: str = DEFAULT_URI,
        user: str = DEFAULT_USER,
        password: str = DEFAULT_PASSWORD,
    ) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def run(self, query: str, **params: Any) -> list[dict]:
        with self._driver.session() as session:
            result = session.run(query, **params)
            return [dict(record) for record in result]

    def init_constraints(self) -> None:
        """创建唯一约束（幂等，可重复调用）。

        注意：现在需要按 user_id 隔离数据，所以唯一约束改为 (text, user_id) 组合。
        先删除旧的单属性约束，再创建新的复合约束。
        """
        # 删除旧的单属性约束（如果存在）
        self.run("DROP CONSTRAINT word_text_unique IF EXISTS")
        self.run("DROP CONSTRAINT category_name_unique IF EXISTS")

        # 创建新的复合唯一约束：(text, user_id) 和 (name, user_id)
        self.run(
            "CREATE CONSTRAINT word_text_user_unique IF NOT EXISTS "
            "FOR (w:Word) REQUIRE (w.text, w.user_id) IS UNIQUE"
        )
        self.run(
            "CREATE CONSTRAINT category_name_user_unique IF NOT EXISTS "
            "FOR (c:Category) REQUIRE (c.name, c.user_id) IS UNIQUE"
        )
