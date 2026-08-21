"""配置加载：从 config/ 目录读取 yaml 配置。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class LLMConfig(BaseModel):
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout: int = 60


class AffixInfo(BaseModel):
    """词缀信息：词缀本身 + 中英含义。"""
    affix: str
    meaning_cn: str = ""
    meaning_en: str = ""


class AffixConfig(BaseModel):
    """词缀配置。支持两种格式：
    - 旧格式：prefixes: ["un", "re", ...]
    - 新格式：prefixes: [{affix: "un", meaning_cn: "不", meaning_en: "not"}, ...]
    两种格式可以混用。
    """
    prefixes: list[AffixInfo] = Field(default_factory=list)
    suffixes: list[AffixInfo] = Field(default_factory=list)

    @field_validator("prefixes", "suffixes", mode="before")
    @classmethod
    def _normalize_affixes(cls, v: list) -> list:
        """把字符串格式转为 AffixInfo，向后兼容旧配置。"""
        result = []
        for item in v:
            if isinstance(item, str):
                result.append({"affix": item, "meaning_cn": "", "meaning_en": ""})
            elif isinstance(item, dict):
                result.append(item)
            else:
                result.append(item)
        return result

    def get_prefix_meaning(self, affix: str) -> AffixInfo | None:
        """按前缀查表返回含义。"""
        for info in self.prefixes:
            if info.affix == affix:
                return info
        return None

    def get_suffix_meaning(self, affix: str) -> AffixInfo | None:
        """按后缀查表返回含义。"""
        for info in self.suffixes:
            if info.affix == affix:
                return info
        return None

    # 保持向后兼容：automake.py 里用 self.prefixes / self.suffixes 作为字符串列表
    @property
    def prefix_texts(self) -> list[str]:
        """返回所有前缀文本（供 automake.py 使用）。"""
        return [info.affix for info in self.prefixes]

    @property
    def suffix_texts(self) -> list[str]:
        """返回所有后缀文本（供 automake.py 使用）。"""
        return [info.affix for info in self.suffixes]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_llm_config() -> LLMConfig:
    data = _load_yaml(CONFIG_DIR / "llm.yaml")
    return LLMConfig(**data.get("llm", {}))


def load_affix_config() -> AffixConfig:
    data = _load_yaml(CONFIG_DIR / "affixes.yaml")
    return AffixConfig(**data)
