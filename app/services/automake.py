"""autoMake 核心循环：种子单词 -> LLM 生成例句 -> 新单词入图 -> 自生长。

一轮循环：
1. 确保分类节点存在
2. 确保种子单词入图（Word + BELONGS_TO，带释义）
3. LLM 根据种子生成 n 条该分类例句（返回例句 + 翻译 + 句内实词的词形/释义）
4. 把 LLM 返回的实词（原形 + 释义）入图，新词建词缀边
5. 建例句边（Sentence + CONTAINS）

由 LLM 负责词形还原（asserting -> assert），新单词即 LLM 返回的实词，
不再用本地正则提取，这样每个入图的词都自带释义、且归一到原形。
新单词作为下一轮候选种子，实现两张图的自生长。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import db as db_module
from app.config import AffixConfig
from app.models import graph
from app.models.schemas import WordInfo
from app.services.llm import LLMClient
from app.services.weight import DEFAULT_INTENSITY, select_seeds


class AutoMake:
    """autoMake 核心编排。"""

    def __init__(
        self,
        gdb: db_module.GraphDB,
        llm: LLMClient,
        affixes: AffixConfig | None = None,
    ) -> None:
        self.gdb = gdb
        self.llm = llm
        self.prefixes = affixes.prefixes if affixes else []
        self.suffixes = affixes.suffixes if affixes else []

    def ensure_category(self, name: str, description: str = "") -> None:
        self.gdb.run(graph.MERGE_CATEGORY, name=name, description=description)

    def existing_words(self) -> set[str]:
        return {r["text"] for r in self.gdb.run(graph.GET_ALL_WORDS)}

    @staticmethod
    def _to_word_info(seed: WordInfo | str) -> WordInfo:
        if isinstance(seed, WordInfo):
            return WordInfo(
                word=seed.word.strip().lower(),
                pos=seed.pos,
                definition_cn=seed.definition_cn,
                definition_en=seed.definition_en,
            )
        return WordInfo(word=str(seed).strip().lower())

    def ensure_seed_words(self, seeds: list[WordInfo | str], category: str) -> None:
        for seed in seeds:
            wi = self._to_word_info(seed)
            if not wi.word:
                continue
            self.gdb.run(
                graph.MERGE_WORD,
                text=wi.word,
                pos=wi.pos,
                definition_cn=wi.definition_cn,
                definition_en=wi.definition_en,
            )
            self.gdb.run(graph.LINK_WORD_CATEGORY, text=wi.word, category=category)

    def pick_seeds(
        self,
        category: str,
        intensity: float = DEFAULT_INTENSITY,
        k: int = 5,
        focus: str | None = None,
    ) -> list[WordInfo | str]:
        """按收敛强度自动选出本轮种子，无需人工勾选。

        强度高 = 收敛（取图中高权重核心词），强度低 = 扩张（取低权重边缘词，
        多为上一轮新入图的词）——这一步把 `run()` 产出的 `new_words` 自动
        回灌成下一轮种子，闭合自生长循环。

        `focus` 非空时进入**焦点词模式**（图页面点单词上的「+」）：该词必定作为
        种子，其余 k-1 个「陪衬词」仍按强度取样——强度高则陪高权重核心词
        （例句更依赖高频词），强度低则陪边缘生词（例句带出更多新词）。

        该分类在图中还没有单词（冷启动）且无焦点词时，回退 LLM 凭分类名生成种子。
        """
        focus_word = (focus or "").strip().lower()
        if focus_word:
            companions = select_seeds(
                self.gdb,
                category=category,
                intensity=intensity,
                k=max(0, k - 1),
                exclude={focus_word},
            )
            return [focus_word] + [c["text"] for c in companions]

        picked = select_seeds(self.gdb, category=category, intensity=intensity, k=k)
        if picked:
            return [p["text"] for p in picked]
        return self.llm.generate_top_words(category, k)

    def run(
        self,
        category: str,
        seeds: list[WordInfo | str],
        n: int = 10,
        description: str = "",
    ) -> dict:
        """执行一轮 autoMake，返回本轮结果 dict。"""
        self.ensure_category(category, description)
        self.ensure_seed_words(seeds, category)
        seed_texts = [self._to_word_info(s).word for s in seeds]

        sentence_infos = self.llm.generate_sentences(seed_texts, category, n)

        known = self.existing_words()
        new_words: list[str] = []
        created_at = datetime.now(timezone.utc).isoformat()

        for si in sentence_infos:
            self.gdb.run(
                graph.MERGE_SENTENCE,
                text=si.sentence,
                translation=si.translation,
                created_at=created_at,
            )
            self.gdb.run(graph.LINK_SENTENCE_CATEGORY, text=si.sentence, category=category)
            for wi in si.words:
                word = wi.word.strip().lower()
                if not word:
                    continue
                is_new = word not in known
                if is_new:
                    self.gdb.run(
                        graph.MERGE_WORD,
                        text=word,
                        pos=wi.pos,
                        definition_cn=wi.definition_cn,
                        definition_en=wi.definition_en,
                    )
                    self.gdb.run(graph.LINK_WORD_CATEGORY, text=word, category=category)
                    known.add(word)
                    new_words.append(word)
                self.gdb.run(graph.LINK_SENTENCE_WORD, text=si.sentence, word=word)
                if is_new:
                    self._link_affixes(word)

        return {
            "category": category,
            "seeds": seed_texts,
            "sentences": [si.sentence for si in sentence_infos],
            "new_words": new_words,
        }

    def _link_affixes(self, word: str) -> None:
        """为新单词与图中已有单词按词缀清单建 SHARES_PREFIX / SHARES_SUFFIX 边。"""
        for prefix in self.prefixes:
            if not word.startswith(prefix):
                continue
            for other in self._words_with_prefix(prefix):
                if other != word:
                    self.gdb.run(graph.LINK_SHARES_PREFIX, a=word, b=other, affix=prefix)
        for suffix in self.suffixes:
            if not word.endswith(suffix):
                continue
            for other in self._words_with_suffix(suffix):
                if other != word:
                    self.gdb.run(graph.LINK_SHARES_SUFFIX, a=word, b=other, affix=suffix)

    def _words_with_prefix(self, prefix: str) -> list[str]:
        return [r["text"] for r in self.gdb.run(graph.WORDS_WITH_PREFIX, prefix=prefix)]

    def _words_with_suffix(self, suffix: str) -> list[str]:
        return [r["text"] for r in self.gdb.run(graph.WORDS_WITH_SUFFIX, suffix=suffix)]
