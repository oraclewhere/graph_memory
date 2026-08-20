"""业务数据模型（Pydantic）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Category(BaseModel):
    name: str
    description: str = ""


class Word(BaseModel):
    text: str
    pos: str = ""
    definition_cn: str = ""
    definition_en: str = ""
    frequency: int = 0
    memory_strength: float = 0.0
    last_reviewed_at: str = ""


class Sentence(BaseModel):
    text: str
    translation: str = ""


class AutoMakeResult(BaseModel):
    category: str
    seeds: list[str] = Field(default_factory=list)
    sentences: list[str] = Field(default_factory=list)
    new_words: list[str] = Field(default_factory=list)


# --- LLM 结构化返回模型 ---


class WordInfo(BaseModel):
    """LLM 返回的单词：原形（lemma）+ 词性 + 释义。"""

    word: str
    pos: str = ""
    definition_cn: str = ""
    definition_en: str = ""


class SentenceInfo(BaseModel):
    """LLM 返回的例句：英文 + 中文翻译 + 句中的实词（原形+释义）。"""

    sentence: str
    translation: str = ""
    words: list[WordInfo] = Field(default_factory=list)
