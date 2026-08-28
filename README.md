# graph_memory - 英文单词记忆图

一个基于图结构的智能单词记忆系统。通过 LLM 自动生成例句，单词在例句中自然关联，形成两张互相促进的知识图谱。

## 核心特性

**自生长循环**：种子单词 → LLM 生成例句 → 句中新生词自动入图 → 循环扩张

**双图结构**：
- **例句图**：单词 ↔ 例句 ↔ 分类
- **单词图**：通过共享词缀（前缀/后缀）互相关联

**三种学习模式**：
- **探索模式**：可视化知识图谱，点击查看释义，支持搜索和多种排布方式
- **复习模式**：字母填空复习，根据记忆度和权重智能排序
- **记忆模式**：逐字母揭示 → 翻转卡片看释义 → 归位测试（匹配释义/填入句中/释义选词）

**智能算法**：
- 收敛强度控制：滑块调节种子选取策略，平衡「巩固核心」与「扩张新词」
- 艾宾浩斯遗忘曲线：记忆度实时衰减，优先推送遗忘单词
- 度中心性权重：基于六度空间理论评估单词重要度

**多用户隔离**：每个用户的图数据完全独立，支持自定义 LLM API 配置

## 技术栈

- **后端**：Python 3.10+ / FastAPI
- **图存储**：Neo4j（Cypher 查询）
- **用户数据**：MySQL + SQLAlchemy + JWT 认证
- **前端**：原生 HTML/CSS/JS + Cytoscape.js 可视化
- **LLM**：OpenAI 兼容接口（支持全局配置和用户自定义）

## 快速开始

```bash
# 1. 安装依赖（需 Python 3.10+）
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 启动数据库（Neo4j + MySQL）
docker compose up -d

# 3. 配置 LLM：复制模板并填入 api_base / api_key / model
cp config/llm.example.yaml config/llm.yaml

# 4. 终端快速验证 autoMake（可选）
python -m app.cli

# 5. 启动 Web 服务
uvicorn app.main:app --reload
```

访问 http://localhost:8000 开始使用。

## 截图

*待补充*

## 文档

- [架构说明](docs/ARCHITECTURE.md) — 分层架构图、模块依赖图、数据模型
- [数据流](docs/DATAFLOW.md) — 全局数据流、写路径、读路径
- [流程图](docs/FLOWCHART.md) — 登录、autoMake、复习等核心流程

## License

MIT
