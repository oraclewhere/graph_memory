# graph_memory 项目文档

## 1. 项目概述

graph_memory 是一个**英文单词记忆图服务**，核心机制是 `autoMake` 自生长循环：

> **种子单词 → LLM 生成例句 → 例句中的新单词入图 → 新单词再作为种子**，如此反复，逐步长出两张互相促进的图。

- **例句图**：单词 ↔ 例句 ↔ 分类（学习内容按主题组织）
- **单词图**：单词之间通过共享英文前缀/后缀互相关联（记忆联想）

**技术栈**：Python 3.10+ · FastAPI · Neo4j · 可配置 LLM（OpenAI 兼容接口）

**关键设计**：LLM 在生成例句时**一并返回**每个实词的「原形（lemma）+ 词性 + 中文释义 + 英文定义」以及例句的中文翻译。词形还原由 LLM 完成（`asserting` → `assert`），避免屈折形式被拆成多个节点、也保证每个词都有释义。

---

## 2. 项目文件功能介绍

```
graph_memory/
├── CLAUDE.md                  # 给 Claude Code 的开发指南（命令、架构、注意事项）
├── README.md                  # 项目简介与快速开始
├── docs/PROJECT.md            # 本文档（项目文档）
├── requirements.txt           # Python 依赖清单
├── docker-compose.yml         # Neo4j 容器定义
├── conftest.py                # pytest 配置（让 `import app` 可用）
├── config/
│   ├── llm.yaml               # LLM 配置（api_base/api_key/model，含密钥，已 gitignore）
│   ├── llm.example.yaml       # LLM 配置模板
│   └── affixes.yaml           # 英文词缀清单（前缀/后缀，可扩展）
├── app/
│   ├── main.py                # FastAPI 应用入口（/ 首页 + /graph 图视图 + /static 静态资源）
│   ├── cli.py                 # terminal 交互入口（快速验证 autoMake）
│   ├── config.py              # 加载 config/ 下的 yaml 配置
│   ├── db.py                  # Neo4j 连接封装 + 约束初始化
│   ├── models/
│   │   ├── schemas.py         # Pydantic 模型（业务模型 + LLM 结构化返回模型）
│   │   └── graph.py           # 图节点/边常量 + 全部 Cypher 查询
│   ├── api/
│   │   └── routes.py          # FastAPI 路由（graph/categories/candidate-words/automake/rank/review）
│   ├── static/
│   │   ├── notes.html         # 首页（笔记列表 + 半自动生成图）
│   │   ├── index.html         # 图视图（子图可视化 + 单词填空）
│   │   └── cytoscape.min.js   # 图可视化库（本地化，避免依赖外网 CDN）
│   └── services/
│       ├── automake.py        # ★ autoMake 核心自生长循环
│       ├── llm.py             # LLM 客户端（OpenAI 兼容，返回结构化释义）
│       ├── weight.py          # 权重模块（单词重要度，实时计算 + 推送排序）
│       ├── memory.py          # 记忆度模块（艾宾浩斯遗忘曲线）
│       ├── graph_query.py     # 图结构查询（导出节点/边）
│       ├── review.py          # 关联审查（预留）
│       └── rumination.py      # 反刍（预留）
└── tests/
    ├── test_automake.py       # autoMake 单元测试（FakeGraphDB + FakeLLM）
    ├── test_seeds.py          # 收敛强度选种子单元测试（强度语义 + 焦点词模式 + 冷启动回退）
    ├── test_memory.py         # 记忆度 + 推送排序单元测试
    └── test_graph_query.py    # 图结构查询单元测试（含子图过滤、例句记忆度均值）
```

**分层职责**：

| 层 | 目录 | 职责 |
|---|---|---|
| 入口层 | `main.py` / `cli.py` | Web 服务入口 / 终端交互入口 |
| API 层 | `api/` | HTTP 路由（预留） |
| 服务层 | `services/` | 业务逻辑：autoMake、LLM、权重、记忆度、图查询、审查、反刍 |
| 模型层 | `models/` | 数据模型 + 图结构定义 |
| 基础设施 | `config.py` / `db.py` | 配置加载 / 数据库访问 |

---

## 3. 核心代码讲解

### 3.1 autoMake 核心循环（`app/services/automake.py`）

这是整个项目的心脏。`AutoMake.run()` 编排一轮完整循环：

```python
def run(self, category, seeds, n=10, description=""):
    # 1. 确保分类节点存在
    self.ensure_category(category, description)

    # 2. 确保种子单词入图（Word 节点 + BELONGS_TO 边，带释义）
    self.ensure_seed_words(seeds, category)
    seed_texts = [self._to_word_info(s).word for s in seeds]

    # 3. LLM 生成 n 条例句（返回 例句 + 翻译 + 句内实词的原形/词性/释义）
    sentence_infos = self.llm.generate_sentences(seed_texts, category, n)

    known = self.existing_words()      # 图中已有单词
    new_words = []

    # 4. 逐句处理
    for si in sentence_infos:
        # 建例句节点（含中文翻译）
        self.gdb.run(graph.MERGE_SENTENCE, text=si.sentence,
                     translation=si.translation, created_at=...)
        self.gdb.run(graph.LINK_SENTENCE_CATEGORY, ...)

        # 5. 把 LLM 返回的实词入图（原形 + 释义）
        for wi in si.words:
            word = wi.word.strip().lower()
            is_new = word not in known
            if is_new:
                self.gdb.run(graph.MERGE_WORD, text=word, pos=wi.pos,
                             definition_cn=wi.definition_cn,
                             definition_en=wi.definition_en)
                self.gdb.run(graph.LINK_WORD_CATEGORY, ...)
                known.add(word)
                new_words.append(word)
            # 例句 -> 单词（CONTAINS 边），无论新旧都建
            self.gdb.run(graph.LINK_SENTENCE_WORD, ...)
            if is_new:                      # 只对新词建词缀边
                self._link_affixes(word)

    return {"category": category, "seeds": seed_texts,
            "sentences": [...], "new_words": new_words}
```

**关键点**：
- **新单词由 LLM 返回的 `words` 驱动**（不再本地正则提取）。每个入图的词都自带释义、且已归一到原形。
- **词形还原由 LLM 负责**：例句里出现 `asserting`，LLM 返回 `word="assert"`（原形），这样种子词 `assert` 能正确匹配到例句，不会产生孤立的重复节点。
- **`new_words` 是自生长的关键**——它作为下一轮候选种子，驱动图持续扩张。回灌方式**不是**调用方手动传回，而是：新词入图后度中心性最低，下一轮 `pick_seeds` 在低强度（扩张）下自然把它们选中（见 3.4）。

**种子从哪来**（`pick_seeds`）：

```python
def pick_seeds(self, category, intensity=0.5, k=5):
    picked = select_seeds(self.gdb, category=category, intensity=intensity, k=k)
    if picked:
        return [p["text"] for p in picked]      # 图里有词：按收敛强度取样
    return self.llm.generate_top_words(category, k)   # 冷启动：LLM 凭分类名生成
```

三条路径：调用方传 `seeds`（手动勾选）→ 按强度自动选（自生长主路径）→ 冷启动回退 LLM。
- **只对新词建词缀边**（`if is_new`），避免对已有单词重复计算。

**词缀建边**（`_link_affixes`）：

```python
def _link_affixes(self, word):
    for prefix in self.prefixes:
        if not word.startswith(prefix):
            continue
        for other in self._words_with_prefix(prefix):   # 查图里同前缀的单词
            if other != word:
                self.gdb.run(graph.LINK_SHARES_PREFIX, a=word, b=other, affix=prefix)
    for suffix in self.suffixes:                        # 后缀同理
        ...
```

- 前缀用 `STARTS WITH`、后缀用 `ENDS WITH` 在图中查找共享词缀的单词，两两建边。
- 词缀清单来自 `config/affixes.yaml`，**v1 是简单字符串匹配**（如 `un` 会同时匹配 `under`），有噪音，后续可升级词形/词根分析。

### 3.2 LLM 客户端（`app/services/llm.py`）

封装任意 OpenAI 兼容接口，返回**结构化结果**（含释义）：

```python
class LLMClient:
    def __init__(self, config=None):
        self.config = config or load_llm_config()
        self._client = OpenAI(
            base_url=self.config.api_base,   # 如 https://api.deepseek.com
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )

    def generate_top_words(self, requirement, n) -> list[WordInfo]:
        # 生成该领域 top N 高频动词/名词，返回 [{word, pos, definition_cn, definition_en}]

    def generate_sentences(self, seeds, category, n) -> list[SentenceInfo]:
        # 生成 n 条例句，返回 [{sentence, translation, words: [WordInfo]}]

    def generate_definitions(self, words) -> list[WordInfo]:
        # 为手动输入的种子词补词性 + 释义
```

**结构化返回模型**（`app/models/schemas.py`）：

```python
class WordInfo(BaseModel):
    word: str             # 原形（lemma）
    pos: str = ""         # 词性
    definition_cn: str = ""   # 中文释义
    definition_en: str = ""   # 英文定义

class SentenceInfo(BaseModel):
    sentence: str         # 英文例句
    translation: str = "" # 中文翻译
    words: list[WordInfo] = []  # 句内实词（原形+释义）
```

**容错解析**（`_parse_json`）——LLM 输出可能带 ```` ```json ```` 代码块，或格式略偏，这里做了统一处理：去掉代码块包裹 → 尝试直接 `json.loads` → 失败则正则提取首个 `[...]` / `{...}` 再解析。

### 3.3 Neo4j 连接（`app/db.py`）

```python
class GraphDB:
    def __init__(self, uri="bolt://localhost:7687", user="neo4j", password="password"):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def run(self, query, **params) -> list[dict]:
        with self._driver.session() as session:
            result = session.run(query, **params)
            return [dict(record) for record in result]   # 统一返回 list[dict]

    def init_constraints(self):
        # 创建 Word.text / Category.name 唯一约束（幂等）
```

- `run()` 统一返回 `list[dict]`，调用方直接遍历，屏蔽了 Neo4j Result 对象的生命周期问题。
- 这样测试里的 `FakeGraphDB` 可以精确模拟同一接口。

### 3.4 权重模块（`app/services/weight.py`）

```python
def compute_weights(gdb):
    records = gdb.run(graph.ALL_WORD_DEGREES)   # 度中心性查询
    return [{"text": r["text"], "weight": r["degree"]} for r in records]
```

- **依据**：六度空间理论——一个单词关联的节点越多，越核心，记忆收益越高。
- **实时计算**：不存权重属性，查询时现场算（v1 用度中心性，即关联边数量；后续可升级 GDS PageRank）。
- **两个用途**：① 按艾宾浩斯曲线复习时优先推高权重词（`rank_words`）；② 按「收敛强度」选下一轮种子（`select_seeds`）。

**收敛强度选种子**（`select_seeds`）——**自生长的方向盘**：

```python
def select_seeds(gdb, category=None, intensity=0.5, k=5, exclude=None):
    # 1. 取该分类内每个词的度中心性（CATEGORY_WORD_DEGREES），归一化到 0~1
    # 2. 取 |weight_norm - intensity| 最小的 k 个   ← 滑块停哪就从哪取种子
    # 3. 同距离时「高权重优先 → 字母序」兜底，保证稳定可测
    # 4. 该分类无词（冷启动）返回 []，由 AutoMake.pick_seeds 回退 LLM
    # 5. exclude 里的词不参与取样（焦点词模式排除自身），但仍参与归一化基准
```

| 强度 | 取到的词 | 效果 |
|---|---|---|
| 高（→1）**收敛** | 度中心性最高的核心词 | 例句围着老词转，句中实词多半已在图里，新词少 → **图变密**，加固既有关联 |
| 中（≈0.5） | 权重谱腰部的词 | 半收敛半扩张 |
| 低（→0）**扩张** | 度最低的边缘词（多为上一轮刚入图、只挂一条例句的新词） | 围着生词造句，拽出大量新词 → **图长大** |

**闭环关键**：`run()` 产出的 `new_words` 入图后度最低，低强度下会被自动选成下一轮种子，**调用方不需要手动把 `new_words` 回灌**——这正是「新单词再作为种子」这半段循环的落地方式。

**焦点词模式**（`pick_seeds(..., focus="reform")`）：图页面点某个单词上的「＋」时，该词**必定**作为种子且排第一，其余 k-1 个「陪衬词」仍按强度取样：

```python
if focus_word:
    companions = select_seeds(gdb, category, intensity, k=k-1, exclude={focus_word})
    return [focus_word] + [c["text"] for c in companions]
```

此时滑块的含义变成「这条例句要多依赖高权重词还是少依赖」——高则陪核心高频词，低则陪边缘生词。焦点词自身就是合法种子，所以这条路**不会触发 LLM 冷启动**。

**滑块该放在哪一页**：强度只在图已经长出来之后才有意义——冷启动时图里一个词都没有，`select_seeds` 返回 `[]` 直接回退 LLM，滑块拖到哪都一样。所以滑块属于**图页面**（让已有的图继续长），不属于首页（从零建图）。

**推送排序**（`rank_words`）：

```python
def rank_words(gdb, half_life_days=7.0, limit=None):
    # 1. 度中心性 → 归一化到 0~1（除以最大度）
    # 2. 每个词的记忆度（艾宾浩斯曲线，见 3.5）
    # 3. score = weight_norm × (1 - memory_strength)   ← 重要度 × 遗忘比例
    # 4. 按 score 降序 = 最该先复习的词
```

- 权重高 + 记忆度低（重要但忘了）→ 高分，优先推送。
- 权重低或已记住 → 低分，靠后。

### 3.5 记忆度模块（`app/services/memory.py`）

根据**艾宾浩斯遗忘曲线**计算单词当前的记忆程度：

```python
memory_strength = e^(-Δt / half_life)
```

- `Δt` = 距上次学习/复习的天数；`half_life` = 记忆半衰期，默认 **7 天**（可调）。
- `memory_strength ∈ [0, 1]`：新词入图时 `0.0`（从未复习），复习成功后 `1.0`，随时间指数衰减。
- Word 节点存 `last_reviewed_at`（时间锚点），记忆度**查询时实时计算**，不存过期值。
- 复习后重置为 1.0（由 `POST /api/review` 触发）。

### 3.6 图结构查询与 API（`app/services/graph_query.py` + `app/api/routes.py`）

`GET /api/graph` 返回图（供前端可视化），可选 `?category=` 只返回该分类子图：

```python
{
  "nodes": [{"id": "word:analyze", "label": "Word", "properties": {...}},
            {"id": "sentence:...", "label": "Sentence", "properties": {...}},
            {"id": "category:考研英语", "label": "Category", "properties": {...}}],
  "edges": [{"source": "word:analyze", "target": "category:考研英语", "type": "BELONGS_TO"}, ...]
}
```

- `id` 格式：`word:<text>` / `sentence:<text>` / `category:<name>`。
- Word 节点的 `properties.memory_strength` 为实时计算的记忆度。
- Sentence 节点的 `properties.memory_strength` = 所含词记忆度均值；`properties.words` = 句内实词原形列表（例句弹窗点击跳转用）。
- 指定 `category` 时用 `GET_CATEGORY_WORDS` / `GET_CATEGORY_SENTENCES` / `GET_CATEGORY_BY_NAME` 取该分类节点，并剔除两端不在子图内的边。

**完整 API 清单**：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/graph?category=` | 返回图（可选子图），Word/Sentence 带实时记忆度 |
| GET | `/api/categories` | 返回所有分类及统计（笔记列表） |
| POST | `/api/candidate-words` | LLM 生成候选种子单词（只调 LLM、不写库），body `{category, n}` |
| GET | `/api/seeds?category=&intensity=&k=&focus=` | 预览按收敛强度选出的种子（只读图、不调 LLM），返回 `{words, intensity, focus, cold_start}`；带 `focus` 时返回陪衬词 |
| POST | `/api/automake` | 执行一轮 autoMake 并写库，body `{category, seeds, n_sentences, description, intensity, n_seeds, focus_word}`；`seeds` 为空即按强度自动选种子，再带 `focus_word` 即焦点词模式 |
| GET | `/api/rank?limit=N` | 返回推送复习顺序（见 3.4） |
| POST | `/api/review` | 复习成功重置记忆度，返回下一个待复习词 |
| GET | `/api/health` | 健康检查 |

### 3.7 前端（`app/static/`）

两个单文件页面，复用同一套暗色设计变量，用 Cytoscape.js（已本地化到 `static/cytoscape.min.js`）：

**职责划分**：首页只管「从零建一张图」（冷启动，无滑块），图页面才管「让图继续长」（增词，有滑块）。

**`notes.html`（首页 `/`）—— 笔记列表 + 新建笔记（冷启动）**

- 输入分类 + 可选描述 + 例句数，「生成候选单词」调 `POST /api/candidate-words`，把返回的候选渲染成带勾选列表（词性 + 中文释义）。
- 勾选种子后点「生成图」调 `POST /api/automake`（带 `seeds`），成功后刷新笔记列表。
- 笔记列表来自 `GET /api/categories`，一个分类一条笔记（显示名称、描述、单词数、例句数），点击跳转 `/graph?category=<分类名>`。

**`index.html`（图视图 `/graph`）—— 子图可视化 + 填空记忆闭环 + 增词**

- 读取 `?category=` 参数只显示该分类子图（无参数则整图）。
- **节点亮度 = 记忆度**：Word 节点用单一蓝色从暗（记忆度低）到亮（记忆度高）；Category 橙色、Sentence 灰色。
- **点击单词节点**：右侧浮出填空面板（显示「词性 / 中文释义 / 英文释义」），面板跟随节点移动（绑定 `pan zoom`），用户填英文提交。
- **答对**：调 `POST /api/review` 重置记忆度 → 节点变亮 → 自动跳到 rank 返回的下一个待复习词；**答错**弹窗询问「显示正确答案 / 再试一次」。
- **点击例句节点**：弹窗显示英文例句 + 中文翻译 + 句内实词（词性/中英释义），句中单词可点击跳转到对应 Word 节点；Esc 退出。
- **右上角「＋」——给整张图增词**：弹窗提示「是否增加新的单词？」，滑块标注为「例句对高权重单词的依赖程度」（左「少依赖：挑边缘生词，长出更多新词」↔ 右「多依赖：围绕核心高频词」），`oninput` 防抖 250ms 调 `GET /api/seeds` **实时显示会选中哪些种子及其度数**；确认后以 `seeds: []` + `intensity` 调 `POST /api/automake`，完成后 `reloadGraph()` 销毁并重建 Cytoscape 实例，新长出来的词立刻出现在图上。
- **单词面板上的「＋」——围绕该词造句**：复用同一个弹窗，额外带 `focus_word`，滑块此时控制陪衬词取核心词还是生词。
- 两个「＋」都需要明确分类（写库要落到某个 Category），**整图视图（URL 无 `?category=`）下隐藏**。
- **邻接高亮**：点击节点后其邻接节点高亮、其余变暗。
- `reloadGraph()` 期间 `state.cy` 会短暂为 `null`（destroy 后、重建前），`closeQuiz` / `closeSentencePanel` / 面板跟随解绑回调都加了空值守卫，避免此刻按 Esc 抛错。

---

## 4. 图存储结构（Neo4j）

### 4.1 节点（Node）

| 标签 | 属性 | 说明 |
|---|---|---|
| `Category` | `name`（唯一）、`description` | 分类，可多个，如「考研英语」「科技词汇」 |
| `Word` | `text`（唯一）、`pos`、`definition_cn`、`definition_en`、`frequency`、`memory_strength`、`last_reviewed_at` | 英文单词原形；中英释义；出现次数；记忆度（0~1，实时计算）；上次复习时间 |
| `Sentence` | `text`、`translation`、`created_at` | 例句英文 + 中文翻译 |

### 4.2 关系（Relationship）

| 类型 | 方向 | 属性 | 含义 |
|---|---|---|---|
| `BELONGS_TO` | `(Word)→(Category)` | — | 单词属于分类 |
| `BELONGS_TO` | `(Sentence)→(Category)` | — | 例句属于分类 |
| `CONTAINS` | `(Sentence)→(Word)` | — | 例句包含单词 |
| `SHARES_PREFIX` | `(Word)→(Word)` | `affix` | 共享同一前缀 |
| `SHARES_SUFFIX` | `(Word)→(Word)` | `affix` | 共享同一后缀 |

### 4.3 结构示意图

```
                    ┌────────────────────────────┐
                    │   Category（考研英语）      │
                    └────────────────────────────┘
                     ▲  BELONGS_TO      ▲  BELONGS_TO
                     │                  │
        ┌────────────┴───┐        ┌─────┴─────────┐
        │  Word（analyze）│        │ Sentence（例句）│
        └──────┬─────────┘        └──────┬─────────┘
               │  SHARES_PREFIX         │ CONTAINS
               │  (affix: "an")         ▼
               │               ┌────────────────┐
               └──────────────▶│ Word（analysis）│
                               └────────────────┘

  （两个 Word 之间通过 SHARES_PREFIX/SHARES_SUFFIX 边连接，
    构成「单词图」；Word/Sentence/Category 之间构成「例句图」）
```

### 4.4 约束（Constraints）

- `Word.text` 唯一约束（`word_text_unique`）
- `Category.name` 唯一约束（`category_name_unique`）

由 `db.py:init_constraints()` 幂等创建（`IF NOT EXISTS`），在 `cli.py` 启动与 `POST /api/automake` 时调用。

### 4.5 全部 Cypher 查询的位置

集中在 `app/models/graph.py`，例如：

```python
MERGE_WORD = (
    "MERGE (w:Word {text: $text}) ON CREATE SET w.pos = $pos, w.frequency = 0, "
    "w.definition_cn = $definition_cn, w.definition_en = $definition_en RETURN w"
)

MERGE_SENTENCE = (
    "MERGE (s:Sentence {text: $text}) ON CREATE SET s.created_at = $created_at, "
    "s.translation = $translation RETURN s"
)

ALL_WORD_DEGREES = (
    "MATCH (w:Word) OPTIONAL MATCH (w)-[r]-() "
    "RETURN w.text AS text, count(r) AS degree ORDER BY degree DESC"
)
```

---

## 5. 数据流总览

```
用户输入（分类 + 需求/种子）
        │
        ▼
  cli.py / main.py ──────────────► services/automake.py（编排）
                                        │
              ┌─────────────────────────┼──────────────────────────┐
              ▼                         ▼                          ▼
      services/llm.py            db.py（GraphDB）          services/weight.py
      （生成例句+翻译+释义）       （读写 Neo4j）              （计算重要度）
                                        │
                                        ▼
                              models/graph.py 中的 Cypher 查询
                                        │
                                        ▼
                                   Neo4j 图数据库
```

**查询路径**（读侧，与上面的写侧相对）：

```
GET /api/graph?category= ──► services/graph_query.py ──► db.py（导出节点/边，可选子图，Word/Sentence 带实时记忆度）
GET /api/categories       ──► models/graph.py GET_CATEGORY_STATS ──► 分类列表 + 统计
POST /api/candidate-words ──► services/llm.py ──► 候选种子词（不写库）
GET /api/seeds            ──► services/weight.py select_seeds ──► 按强度预览种子（不写库、不调 LLM）
POST /api/automake        ──► services/automake.py ──► 一轮自生长（写库）
GET /api/rank             ──► services/weight.py + memory.py ──► 重要度 × 遗忘比例 排序
```

**自生长闭环**（滑块在图页面，两个「＋」都进这个环）：

```
   图页面右上角「＋」          单词面板「＋」
   （整图增词）               （焦点词模式，该词必定入选）
             │                        │
             └──────────┬─────────────┘
                        ▼
                   收敛强度滑块
                        │
                        ▼
   select_seeds（按权重谱取样）──► 种子单词
             ▲                        │
             │                        ▼
             │                LLM 生成例句
             │                        │
             │                        ▼
             └──── new_words 入图（度最低）◄── 句内实词
                   低强度下自动成为下一轮种子
```

**一句话总结**：入口层收集用户意图 → `automake` 编排「LLM 生成结构化内容」与「图写入」两个动作 → 新词（原形+释义）入图后成为图中的低权重节点，由收敛强度滑块决定下一轮从权重谱哪一段取种子，驱动两张图自生长。
