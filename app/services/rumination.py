"""反刍模块（预留）：对生成结果进行反刍修改（与艾宾浩斯复习无关）。

TODO: 反刍逻辑待定。可能的职责：
- 把已有单词/例句重新喂给 LLM，生成更深层或更难的例句
- 对已有生成结果做二次修改 / 润色
"""


class Rumination:
    """反刍（占位，逻辑待定）。"""

    def __init__(self, llm=None) -> None:
        self.llm = llm

    def ruminate(self, *args, **kwargs):
        raise NotImplementedError("反刍逻辑待定")
