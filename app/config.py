"""配置加载：从 config/ 目录读取 yaml 配置。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class LLMConfig(BaseModel):
    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout: int = 60


class AffixConfig(BaseModel):
    prefixes: list[str] = Field(default_factory=list)
    suffixes: list[str] = Field(default_factory=list)


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
