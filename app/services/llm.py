"""LLM 客户端：OpenAI 兼容接口，base_url 可配置。

兼容 OpenAI / DeepSeek / 通义 / Moonshot 等任何 OpenAI 兼容接口，
只需在 config/llm.yaml 里填 api_base / api_key / model。

返回均为结构化结果：单词带「原形（lemma）+ 词性 + 中英释义」，例句带中文翻译。
由 LLM 负责词形还原（asserting -> assert），避免屈折形式拆成多个节点。
"""
from __future__ import annotations

import json
import re

from openai import OpenAI

from app.config import LLMConfig, load_llm_config
from app.models.schemas import SentenceInfo, WordInfo


class LLMClient:
    """封装 LLM 调用，返回结构化结果。"""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or load_llm_config()
        self._client = OpenAI(
            base_url=self.config.api_base,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )

    def _chat(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,
        )
        return resp.choices[0].message.content or ""

    def generate_top_words(self, requirement: str, n: int) -> list[WordInfo]:
        """根据需求生成该领域 top N 高频动词/名词（含释义）。"""
        system = (
            "You are an English vocabulary expert. "
            "Return ONLY a JSON array, no extra text."
        )
        user = (
            f"Topic: {requirement}. List the top {n} most frequent English verbs and "
            'nouns in this field. Return a JSON array of objects, each: '
            '{"word": "base form", "pos": "verb|noun", '
            '"definition_cn": "中文释义", "definition_en": "English definition"}. '
            "Every word must be in base form (lemma)."
        )
        return self._to_word_infos(self._parse_json(self._chat(system, user)))

    def generate_sentences(self, seeds: list[str], category: str, n: int) -> list[SentenceInfo]:
        """根据种子单词生成 n 条该分类例句（含翻译 + 句内实词释义）。"""
        system = (
            "You are an expert English teacher. "
            "Return ONLY a JSON array, no extra text."
        )
        seed_list = ", ".join(seeds)
        user = (
            f"Write {n} English example sentences about the topic '{category}'. "
            f"Each sentence must contain at least one of these words: {seed_list}. "
            'Return a JSON array of objects, each: {"sentence": "English sentence", '
            '"translation": "中文翻译", "words": [{"word": "base form", '
            '"pos": "verb|noun|adj|adv", "definition_cn": "中文释义", '
            '"definition_en": "English definition"}]}. '
            'In "words", list every content word (noun/verb/adjective/adverb) that appears '
            "in the sentence, excluding function words like the/a/of/to. "
            "Every word must be in base form (lemma)."
        )
        return self._to_sentence_infos(self._parse_json(self._chat(system, user)))

    def generate_definitions(self, words: list[str]) -> list[WordInfo]:
        """为给定单词列表补词性 + 释义（用于手动输入的种子词）。"""
        system = (
            "You are an English vocabulary expert. "
            "Return ONLY a JSON array, no extra text."
        )
        word_list = ", ".join(words)
        user = (
            f"For each of these words, give its base form, part of speech and meanings: "
            f"{word_list}. Return a JSON array of objects, each: "
            '{"word": "base form", "pos": "verb|noun|adj|adv", '
            '"definition_cn": "中文释义", "definition_en": "English definition"}. '
            "Every word must be in base form (lemma)."
        )
        return self._to_word_infos(self._parse_json(self._chat(system, user)))

    @staticmethod
    def _parse_json(raw: str):
        """从 LLM 原始输出解析 JSON，容错处理（去代码块、提取 [...]/{...}）。"""
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        for pat in (r"\[.*\]", r"\{.*\}"):
            m = re.search(pat, raw, flags=re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue
        return None

    @staticmethod
    def _to_word_infos(data) -> list[WordInfo]:
        if isinstance(data, dict):
            for k in ("words", "result", "data"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, str):
                out.append(WordInfo(word=item))
            elif isinstance(item, dict) and item.get("word"):
                out.append(WordInfo(
                    word=str(item["word"]),
                    pos=str(item.get("pos", "")),
                    definition_cn=str(item.get("definition_cn", "")),
                    definition_en=str(item.get("definition_en", "")),
                ))
        return out

    @staticmethod
    def _to_sentence_infos(data) -> list[SentenceInfo]:
        if isinstance(data, dict):
            for k in ("sentences", "result", "data"):
                if isinstance(data.get(k), list):
                    data = data[k]
                    break
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            sentence = item.get("sentence") or item.get("text")
            if not sentence:
                continue
            out.append(SentenceInfo(
                sentence=str(sentence),
                translation=str(item.get("translation", "")),
                words=LLMClient._to_word_infos(item.get("words", [])),
            ))
        return out
