"""terminal 交互入口：快速验证 autoMake 循环。

用法：python -m app.cli
"""
from __future__ import annotations

from app import db as db_module
from app.config import load_affix_config
from app.models.schemas import WordInfo
from app.services.automake import AutoMake
from app.services.llm import LLMClient


def main() -> None:
    gdb = db_module.GraphDB()
    gdb.init_constraints()

    affixes = load_affix_config()
    llm = LLMClient()
    automake = AutoMake(gdb, llm, affixes)

    print("=== graph_memory 快速验证 ===")
    category = input("分类名（如：考研英语 / 科技词汇）: ").strip()
    if not category:
        print("分类名不能为空，退出。")
        gdb.close()
        return
    description = input("分类描述（可空）: ").strip()

    use_llm = input("是否让 LLM 生成 top 单词？(y/n，默认 n 手动输入): ").strip().lower()
    seeds: list[WordInfo] = []
    if use_llm == "y":
        requirement = input("学习需求（如：考研英语高频动词名词）: ").strip()
        n_words = int(input("生成 top N 个单词（默认 10）: ").strip() or "10")
        words = llm.generate_top_words(requirement, n_words)
        if not words:
            print("LLM 未返回候选单词，退出。")
            gdb.close()
            return
        print("LLM 候选单词：")
        for i, w in enumerate(words, 1):
            print(f"  {i}. {w.word}  ({w.pos}) {w.definition_cn}")
        selected = input("选择作为种子的编号（逗号分隔，回车=全部）: ").strip()
        if selected:
            idxs = [int(x) - 1 for x in selected.split(",") if x.strip().isdigit()]
            seeds = [words[i] for i in idxs if 0 <= i < len(words)]
        else:
            seeds = words
    else:
        seeds_raw = input("手动输入种子单词（逗号分隔）: ").strip()
        raw_words = [s.strip() for s in seeds_raw.split(",") if s.strip()]
        if raw_words:
            print("正在为种子词补释义……")
            seeds = llm.generate_definitions(raw_words)

    if not seeds:
        print("没有种子单词，退出。")
        gdb.close()
        return

    n_sent = int(input("生成例句数（默认 10）: ").strip() or "10")

    result = automake.run(
        category=category, seeds=seeds, n=n_sent, description=description
    )

    print("\n=== 本轮结果 ===")
    print(f"分类: {result['category']}")
    print(f"种子: {', '.join(result['seeds'])}")
    print(f"例句 ({len(result['sentences'])} 条):")
    for s in result["sentences"]:
        print(f"  - {s}")
    print(f"新单词 ({len(result['new_words'])} 个): {', '.join(result['new_words'])}")

    gdb.close()


if __name__ == "__main__":
    main()
