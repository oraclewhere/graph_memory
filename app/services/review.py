"""关联审查模块（预留）：审查生成结果。

TODO: 审查逻辑待定。可能的职责：
- 审查 LLM 生成例句是否与分类相关、语法是否正确
- 审查新单词是否真的该加入单词图（去噪 / 去重）
- 自动（LLM 再判断 / 规则）或人工介入
"""


class Review:
    """关联审查（占位，逻辑待定）。"""

    def __init__(self, llm=None) -> None:
        self.llm = llm

    def review(self, *args, **kwargs):
        raise NotImplementedError("关联审查逻辑待定")
