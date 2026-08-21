# 数据流图

> 讲**数据从哪来、经过谁、变成什么形态、落到哪去**。
> 系统组成看 [ARCHITECTURE.md](ARCHITECTURE.md)，分支判断和交互步骤看 [FLOWCHART.md](FLOWCHART.md)。

---

## 1. 全局数据流总览

```mermaid
flowchart LR
    U(("用户"))

    subgraph FE["前端"]
        NH["notes.html"]
        IH["index.html"]
    end

    subgraph BE["FastAPI 服务"]
        R["routes.py"]
        AM["automake"]
        WT["weight"]
        MEM["memory"]
        GQ["graph_query"]
        LC["llm client"]
    end

    LLM["LLM API"]
    NEO[("Neo4j")]

    U -->|"分类名 / 勾选 / 强度 / 答题"| FE
    FE -->|"HTTP JSON"| R

    R --> AM
    R --> WT
    R --> MEM
    R --> GQ

    AM -->|"种子词 + 分类 + 条数"| LC
    LC -->|"prompt"| LLM
    LLM -->|"例句 + 翻译 + 实词释义"| LC
    LC -->|"SentenceInfo 列表"| AM

    AM -->|"Cypher 写"| NEO
    WT -->|"Cypher 读 · 度中心性"| NEO
    MEM -->|"Cypher 读写 · 记忆度"| NEO
    GQ -->|"Cypher 读 · 全图"| NEO

    GQ -->|"nodes + edges"| R
    WT -->|"排序后的词表"| R
    R -->|"JSON"| FE
    FE -->|"Cytoscape 渲染"| U

    style NEO fill:#2d3748,color:#fff
    style LLM fill:#4a3728,color:#fff
```

**三种外部数据源**：用户输入（分类、勾选、强度、答题）、LLM 产出（例句和释义）、Neo4j 存量（已有的词和边）。
**唯一的真相来源是 Neo4j**——记忆度、权重都是从图里**实时算出来的**，不缓存、不落中间态。

---

## 2. 写路径：autoMake 一轮的数据流

这是系统里唯一会写库的路径。数据形态在每一步都发生变化：

```mermaid
flowchart TB
    IN["输入<br/>category · seeds? · intensity · focus? · n"]

    S1["① ensure_category<br/>MERGE Category"]
    S2{"② 种子从哪来"}
    S2A["调用方传入<br/>list of WordInfo"]
    S2B["按强度采样<br/>select_seeds"]
    S2C["LLM 冷启动<br/>generate_top_words"]
    S3["③ ensure_seed_words<br/>MERGE Word + LINK BELONGS_TO"]
    S4["④ LLM generate_sentences<br/>seeds + category + n"]
    S5["⑤ 实词入图<br/>不在 known 集合的 → 新词"]
    S6["⑥ 建例句边<br/>MERGE Sentence + CONTAINS"]
    S7["⑦ 新词建词缀边<br/>SHARES_PREFIX / SHARES_SUFFIX"]
    OUT["返回<br/>category · seeds · sentences · new_words"]

    IN --> S1 --> S2
    S2 -->|"seeds 非空"| S2A
    S2 -->|"seeds 为空 · 图里有词"| S2B
    S2 -->|"seeds 为空 · 图里没词"| S2C
    S2A --> S3
    S2B --> S3
    S2C --> S3
    S3 --> S4 --> S5 --> S6 --> S7 --> OUT

    OUT -.->|"新词度数最低<br/>低强度下自动被选为下轮种子"| S2B

    style OUT fill:#1e3a2f,color:#fff
    style S4 fill:#4a3728,color:#fff
```

### 数据形态变化表

| 阶段 | 数据形态 | 示例 |
|---|---|---|
| 前端提交 | JSON | `{"category":"考研英语","seeds":[],"intensity":0.2,"n_sentences":10}` |
| 路由解析 | `AutoMakeRequest`（Pydantic） | 带默认值：`n_seeds=5`、`focus_word=""` |
| 种子选择后 | `list[str]` 或 `list[WordInfo]` | `["anxiety","reform","exam"]` |
| LLM 请求 | prompt 文本 | "用这些词造 10 个考研英语例句…" |
| LLM 响应 | `list[SentenceInfo]` | 每条含 `sentence`、`translation`、`words[]` |
| 单词条目 | `WordInfo` | `{word:"assert", pos:"v.", definition_cn:"断言", definition_en:"..."}` |
| 落库 | Cypher 参数 | `MERGE (w:Word {text:$text}) SET ...` |
| 响应 | JSON | `{"ok":true,"auto_seeds":true,"new_words":["assert","reform"],...}` |

### 关键点：词形还原在 LLM 侧

LLM 返回的 `words[]` **已经是原形**（`asserting → assert`），不再用本地正则从句子里抠词。
这样每个入图的词都自带词性和中英释义，且不会因为屈折形式（`assert` / `asserts` / `asserting`）
拆成三个节点把图撑散。

### 关键点：`known` 快照决定"新词"

`run()` 在生成例句**之后**、写库**之前**取一次 `existing_words()` 快照。
判定 `is_new` 时对照这个快照并**边写边更新**（`known.add(word)`），
所以同一批例句里重复出现的词只会被算作一次新词，且只建一次词缀边。

---

## 3. 读路径

### 3.1 `GET /api/graph` —— 前端渲染的数据来源

```mermaid
flowchart LR
    REQ["GET /api/graph?category=考研英语"] --> GQ["graph_query.get_graph"]

    GQ --> Q1["查节点<br/>Category / Word / Sentence"]
    GQ --> Q2["查边<br/>BELONGS_TO / CONTAINS / SHARES_*"]
    GQ --> Q3["ALL_WORD_DEGREES<br/>度中心性"]
    GQ --> Q4["memory.memory_strength_at<br/>按 last_reviewed_at 实时衰减"]

    Q1 --> ASM["组装"]
    Q2 --> ASM
    Q3 --> ASM
    Q4 --> ASM

    ASM --> W["Word 节点<br/>+ memory_strength 实时算<br/>+ weight 度中心性"]
    ASM --> S["Sentence 节点<br/>+ memory_strength = 所含词均值<br/>+ weight = 所含实词数<br/>+ words 实词列表"]
    ASM --> RES["nodes + edges"]
    W --> RES
    S --> RES

    RES --> CY["Cytoscape<br/>亮度=记忆度 · 同心圆半径=weight"]
```

**为什么 `weight` 要从后端给**：前端同心圆布局用的 `weight` 和推送排序用的权重
必须是**同一个 `ALL_WORD_DEGREES` 查询**的结果，否则"图上看起来最核心的词"
和"系统推荐先复习的词"会对不上，用户会觉得系统在自相矛盾。
（前端仍保留 `node.degree()` 作为 `weight` 缺失时的兜底。）

### 3.2 `GET /api/rank` —— 推送复习顺序

```mermaid
flowchart LR
    A["ALL_WORD_DEGREES<br/>degree"] --> B["归一化<br/>weight_norm = degree / max_degree"]
    C["last_reviewed_at"] --> D["记忆度<br/>e^(-Δt / 7天)"]
    B --> E["score = weight_norm × (1 - memory_strength)"]
    D --> E
    E --> F["降序<br/>= 最该先复习"]
```

含义直白：**又重要、又快忘光了** 的词排最前。
从没复习过的词 `memory_strength = 0`，所以 `score = weight_norm`——高频核心词天然排在最前面。

### 3.3 `POST /api/review` —— 复习回写

这是除 autoMake 外**唯一会写库**的路径，但只改 Word 节点的两个属性：

```mermaid
sequenceDiagram
    participant U as 用户
    participant IH as index.html
    participant R as routes.py
    participant M as memory.py
    participant W as weight.py
    participant N as Neo4j

    U->>IH: 填对释义 / 点「显示正确答案」
    IH->>R: POST /api/review {"word":"exam"}
    R->>M: review_word(gdb, "exam")
    M->>N: SET memory_strength=1.0,<br/>last_reviewed_at=now
    N-->>M: 更新后的节点
    R->>W: rank_words(gdb, limit=1)
    W->>N: ALL_WORD_DEGREES + 各词记忆度
    N-->>W: 度数
    W-->>R: 下一个待复习词
    R-->>IH: {ok, word, memory_strength, next}
    IH->>IH: 节点变亮
    IH->>U: 自动跳到 next 继续答题
```

一次请求同时完成"记这次复习"和"给下一题"，前端不用再发一次 `/api/rank`。

### 3.4 `GET /api/seeds` —— 滑块的即时预览

```mermaid
flowchart LR
    SL["滑块 oninput<br/>防抖 250ms"] --> REQ["GET /api/seeds<br/>category · intensity · k · focus"]
    REQ --> SS["weight.select_seeds"]
    SS --> NEO[("Neo4j 只读")]
    NEO --> RESP["words 每项含 text weight weight_norm distance<br/>外加 intensity focus cold_start"]
    RESP --> UI["弹窗里列出<br/>这一轮会拿哪些词当种子"]

    style REQ fill:#1e3a2f,color:#fff
```

**这条路只读图，不调 LLM、不写库**——所以可以随手拖滑块，成本只有一次 Cypher 查询。
带 `focus` 时返回的是**陪衬词**（焦点词自身已从采样中排除，由前端单独展示），此时 `cold_start` 恒为 `false`。

---

## 4. 自生长闭环

这是整个项目的核心机制。**闭环不需要任何人工回灌**：

```mermaid
flowchart TB
    A["图里的存量单词<br/>带各自的度中心性"]
    B["按 intensity 在权重光谱上采样<br/>distance = abs(weight_norm - intensity)"]
    C["选出 k 个种子"]
    D["LLM 围绕种子造 n 条例句"]
    E["例句里的实词<br/>不在图里的 = 新词"]
    F["新词入图<br/>只挂 1~2 条边 → 度数最低"]
    G["新词的 weight_norm ≈ 0"]

    A --> B --> C --> D --> E --> F --> G
    G -->|"下一轮 intensity 低时<br/>distance 最小 → 必被选中"| B

    subgraph HI["intensity 高 · 收敛"]
        H1["取核心高频词"] --> H2["例句围着老词转"] --> H3["新词少<br/>图变密"]
    end

    subgraph LO["intensity 低 · 扩张"]
        L1["取边缘低度词"] --> L2["围着生词造句"] --> L3["拽出大量生词<br/>图长大"]
    end

    C -.-> HI
    C -.-> LO

    style G fill:#1e3a2f,color:#fff
```

### 为什么闭环能自动成立

新入图的词只挂着"1 条 `BELONGS_TO` + 1 条 `CONTAINS`"，度数是全图最低的。
`select_seeds` 用 `abs(weight_norm - intensity)` 排序，当 `intensity` 接近 0 时，
这些 `weight_norm ≈ 0` 的新词 `distance` 最小，**自动排到最前面**。

所以调用方**不需要**把上一轮的 `new_words` 传回去——图结构本身就记住了"谁是新词"。

### 滑块该放哪：一个曾经踩过的坑

强度**只在图已经长出来之后才有意义**。冷启动时 `select_seeds` 返回 `[]` 直接回退 LLM，
滑块拖到哪都没区别。所以滑块在**图页面**，不在首页。

首页只管"从零建一张图"（冷启动，半自动勾选），图页面才管"让图继续长"（增词，滑块控制方向）。

---

## 5. 两个"+"的数据流对比

图页面上有两个增词入口，走同一个 `POST /api/automake`，区别只在 `focus_word`：

```mermaid
flowchart TB
    subgraph P1["右上角 + · 整图增词"]
        A1["POST /api/automake<br/>seeds 为空 · intensity 0.3 · 无 focus_word"]
        A2["pick_seeds 按强度采样 k 个"]
        A3["种子 = 强度决定的 k 个词"]
        A1 --> A2 --> A3
    end

    subgraph P2["单词面板的 + · 焦点词模式"]
        B1["POST /api/automake<br/>seeds 为空 · intensity 0.3 · focus_word 为 reform"]
        B2["reform 必定入选且排第一<br/>其余 k-1 个陪衬词 exclude 掉 reform 后按强度取样"]
        B3["种子 = reform 加 k-1 个陪衬词"]
        B1 --> B2 --> B3
    end

    A3 --> C["同一个 automake.run()"]
    B3 --> C
    C --> D["返回 sentences + new_words"]
    D --> E["前端弹窗切到结果视图<br/>本批 N 条例句 · M 个新词<br/>新词渲染成 chip 可点击定位"]
    E --> F["reloadGraph 就地重建 Cytoscape"]
```

焦点词模式下滑块的含义变了：不再控制"选哪些种子"，而是控制**陪衬词是核心词还是生词**——
强度高则围绕焦点词 + 核心高频词造句，强度低则围绕焦点词 + 边缘生词造句。

焦点词本身就是合法种子，所以**这条路永远不走 LLM 冷启动**。

### `exclude` 的一个细节

被 `exclude` 的词**不参与采样，但仍参与归一化基准**（仍算进 `max_degree`）。
否则去掉一个高权重词后，剩余词的 `weight_norm` 会整体被抬高，
"核心度"这把尺子会漂移——同一个 `intensity` 在两次调用里选出不同性质的词。

---

## 6. 数据一致性约定

| 约定 | 原因 |
|---|---|
| 记忆度、权重**不落库**，每次读时实时算 | 记忆度随时间连续衰减，落库就必须定时刷新；度中心性随边变化，落库就必须在每次写边后同步 |
| 只有 `last_reviewed_at` 落库 | 它是衰减曲线的锚点，是唯一需要持久化的状态 |
| 所有 Cypher 集中在 `models/graph.py` | 前端布局和后端排序必须用同一个 `ALL_WORD_DEGREES`，共用常量才能保证口径一致 |
| 所有写库经 `GraphDB.run()` | 单一入口，便于日后加事务、重试、审计 |
| 单词一律 `strip().lower()` 后入图 | `Word.text` 是唯一约束，大小写不统一会造出重复节点 |
