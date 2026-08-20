# graph_memory

英文单词记忆图服务。通过「种子单词 → LLM 生成例句 → 新单词入图 → 再生成」的自生长循环（`autoMake`），逐步长出两张互相促进的图：

- **例句图**：单词 ↔ 例句 ↔ 分类
- **单词图**：单词之间通过共享英文前缀/后缀互相关联

## 快速开始

```bash
# 1. 安装依赖（需 Python 3.10+）
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 启动 Neo4j
docker compose up -d

# 3. 配置 LLM：复制模板并填入 api_base / api_key / model
cp config/llm.example.yaml config/llm.yaml

# 4. 终端快速验证 autoMake
python -m app.cli

# 5. 或启动 Web 服务
uvicorn app.main:app --reload
```

详细架构与命令见 [CLAUDE.md](CLAUDE.md)。
