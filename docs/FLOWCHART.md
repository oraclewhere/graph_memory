# 流程图

> 讲**每一步怎么走、遇到分支怎么判、出错回退到哪**。
> 系统组成看 [ARCHITECTURE.md](ARCHITECTURE.md)，数据形态变化看 [DATAFLOW.md](DATAFLOW.md)。

---

## 1. 登录/注册流程

```mermaid
flowchart TB
    A(["访问任何页面"]) --> B{"localStorage<br/>有 token？"}
    B -->|"没有"| C["跳转 /login"]
    B -->|"有"| D["正常访问"]

    C --> E{"选择操作"}
    E -->|"注册"| F["填写用户名/密码"]
    E -->|"登录"| G["填写用户名/密码"]

    F --> H["POST /api/auth/register"]
    G --> I["POST /api/auth/login"]

    H --> J{"注册成功？"}
    I --> K{"登录成功？"}

    J -->|"是"| L["返回 token + user"]
    J -->|"否 · 用户名已存在"| M["提示错误"]
    M --> F

    K -->|"是"| L
    K -->|"否 · 密码错误"| N["提示错误"]
    N --> G

    L --> O["localStorage.setItem(token)"]
    O --> P["跳转 /"]
    P --> D

    style C fill:#4a3728,color:#fff
    style L fill:#1e3a2f,color:#fff
```

**关键点**：
- 所有页面都有登录检查，未登录跳转 `/login`
- 登录成功返回 JWT token，有效期 24 小时
- token 存储在 `localStorage`，后续请求自动带上

---

## 2. autoMake 一轮完整流程

```mermaid
flowchart TB
    START(["POST /api/automake"]) --> INIT["init_constraints<br/>幂等建唯一约束"]
    INIT --> CAT["ensure_category<br/>MERGE Category name description"]
    CAT --> PICK{"req.seeds 为空？"}

    PICK -->|"否 · 手动模式"| USE["直接用传入的 seeds<br/>auto_seeds = false"]
    PICK -->|"是 · 自动模式"| AUTO["pick_seeds<br/>见第 2 节决策树"]

    USE --> ENSURE
    AUTO --> ENSURE["ensure_seed_words<br/>逐个 MERGE Word + LINK BELONGS_TO"]

    ENSURE --> GEN["llm.generate_sentences<br/>seed_texts + category + n"]
    GEN --> EMPTY{"LLM 返回空？"}
    EMPTY -->|"是"| RETEMPTY["例句为空 新词为空<br/>前端提示没长出新词"]
    EMPTY -->|"否"| SNAP["existing_words<br/>取一次已有单词快照 known"]

    SNAP --> LOOP{"还有例句未处理？"}
    LOOP -->|"是"| MS["MERGE Sentence<br/>text translation created_at"]
    MS --> LSC["LINK Sentence BELONGS_TO Category"]
    LSC --> WLOOP{"该句还有实词未处理？"}

    WLOOP -->|"是"| NORM["word = strip lower"]
    NORM --> BLANK{"空串？"}
    BLANK -->|"是"| WLOOP
    BLANK -->|"否"| ISNEW{"word 在 known 里？"}

    ISNEW -->|"在 · 老词"| LSW
    ISNEW -->|"不在 · 新词"| MW["MERGE Word 带词性和中英释义"]
    MW --> LWC["LINK Word BELONGS_TO Category"]
    LWC --> ADD["known.add · new_words.append"]
    ADD --> LSW["LINK Sentence CONTAINS Word<br/>同时 frequency + 1"]

    LSW --> AFFIX{"是新词？"}
    AFFIX -->|"是"| LINKA["_link_affixes<br/>见第 4 节"]
    AFFIX -->|"否"| WLOOP
    LINKA --> WLOOP

    WLOOP -->|"没有了"| LOOP
    LOOP -->|"没有了"| RET["返回 category seeds sentences new_words"]

    RETEMPTY --> RET
    RET --> CLOSE(["gdb.close · finally"])

    style GEN fill:#4a3728,color:#fff
    style RET fill:#1e3a2f,color:#fff
```

**注意执行顺序**：`existing_words()` 快照取在**生成例句之后、写例句之前**。
如果取得太早（比如在 `ensure_seed_words` 之前），种子词自己会被误判成新词。

---

## 3. 种子选择决策树

`pick_seeds()` 只有三条出路，判断顺序不能换：

```mermaid
flowchart TB
    IN(["pick_seeds<br/>category intensity k focus"]) --> F{"focus 非空？"}

    F -->|"是 · 焦点词模式"| FC["select_seeds<br/>k-1 个 · exclude 焦点词"]
    FC --> FR["返回 焦点词 + k-1 个陪衬词<br/>焦点词排第一"]
    FR --> FNOTE["焦点词本身就是合法种子<br/>这条路永不冷启动"]

    F -->|"否"| SEL["select_seeds<br/>按 intensity 采样 k 个"]
    SEL --> HAS{"选出东西了？"}

    HAS -->|"是 · 图里有词"| NORMAL["返回 k 个词的 text<br/>自生长主路径"]
    HAS -->|"否 · 该分类图里还没词"| COLD["llm.generate_top_words<br/>凭分类名生成 k 个<br/>冷启动回退"]

    style FR fill:#1e3a2f,color:#fff
    style NORMAL fill:#1e3a2f,color:#fff
    style COLD fill:#4a3728,color:#fff
```

| 分支 | 触发条件 | 是否调 LLM | 对应前端入口 |
|---|---|---|---|
| 手动 | `req.seeds` 非空 | 否（种子已定） | 首页勾选后「生成图」 |
| 焦点词 | `seeds` 空 + `focus_word` 非空 | 否 | 图页面单词面板上的「+」 |
| 强度采样 | `seeds` 空 + 图里有词 | 否 | 图页面右上角「+」 |
| 冷启动 | `seeds` 空 + 图里没词 | **是** | 图页面「+」但分类是空的 |

### 一个曾经的 bug：`k=0`

焦点词模式下 `k-1` 可能等于 `0`。原实现写的是 `return scored[:k] if k else scored`，
Python 里 `0` 是假值，会被当成"没传 k"，于是**把整个分类的词全部返回**当种子。
现在改成显式区分 `None` 和 `0`：

```python
if k is None:
    return scored
return scored[:max(0, k)]
```

（对应用例 `test_zero_k_selects_nothing`。）

---

## 4. 收敛强度采样

```mermaid
flowchart TB
    A(["select_seeds<br/>category intensity k exclude"]) --> CLAMP["intensity 钳到 0~1<br/>min(1.0, max(0.0, intensity))"]
    CLAMP --> QUERY{"指定 category？"}
    QUERY -->|"是"| Q1["CATEGORY_WORD_DEGREES"]
    QUERY -->|"否"| Q2["ALL_WORD_DEGREES"]
    Q1 --> REC
    Q2 --> REC{"查到记录了吗？"}

    REC -->|"没有 · 冷启动"| EMPTY["返回空列表<br/>交给 pick_seeds 回退 LLM"]
    REC -->|"有"| MAX["max_w = 最大 degree<br/>为 0 时兜底成 1 防除零"]

    MAX --> SCORE["逐词计算<br/>weight_norm = degree / max_w<br/>distance = abs(weight_norm - intensity)"]
    SCORE --> SKIP["跳过 exclude 里的词<br/>但它们仍算进 max_w 基准"]
    SKIP --> SORT["排序 distance 升序<br/>→ weight 降序<br/>→ 字母序"]
    SORT --> CUT["取前 k 个"]

    style EMPTY fill:#4a3728,color:#fff
```

### 采样直觉

把分类里所有词按归一化权重摊在 0~1 的数轴上，**滑块停在哪，就从哪附近抓词**：

```
weight_norm:  0.0 ────────────────────────────── 1.0
              anxiety  reform   critical   exam
              (2度)    (5度)    (7度)     (16度)
                ↑                            ↑
       intensity=0.0                 intensity=1.0
       扩张：抓边缘生词              收敛：抓核心高频词
       例句带出大量新词              例句围着老词转
       图变大                        图变密
```

排序的三级兜底（`distance` → `-weight` → 字母序）是为了**结果稳定可测**：
同样的图 + 同样的强度，永远选出同样的种子，测试才能断言。

---

## 5. 词缀边构建

```mermaid
flowchart TB
    A(["_link_affixes(word)"]) --> P{"遍历 config/affixes.yaml<br/>的 prefixes"}
    P --> PM{"word.startswith(prefix)？"}
    PM -->|"否"| P
    PM -->|"是"| PQ["WORDS_WITH_PREFIX<br/>查图里所有同前缀词"]
    PQ --> PL{"other != word？"}
    PL -->|"是"| PE["LINK_SHARES_PREFIX<br/>带 affix 属性"]
    PL -->|"否"| P
    PE --> P

    P -->|"遍历完"| S{"遍历 suffixes"}
    S --> SM{"word.endswith(suffix)？"}
    SM -->|"否"| S
    SM -->|"是"| SQ["WORDS_WITH_SUFFIX"]
    SQ --> SL{"other != word？"}
    SL -->|"是"| SE["LINK_SHARES_SUFFIX"]
    SL -->|"否"| S
    SE --> S
    S -->|"遍历完"| END(["结束"])
```

**只对新词建边**（老词的词缀边在它当初入图时已经建过了）。

**v1 的已知噪音**：朴素 `startswith` / `endswith` 字符串匹配，
前缀 `un-` 会把 `under`、`uncle` 也匹配进来。词缀清单只收派生词缀、
不收屈折词缀（`-ing` / `-ed`），避免同一个词的不同形态互连。

---

## 6. 记忆度与复习循环

### 6.1 一个单词的记忆度生命周期

```mermaid
stateDiagram-v2
    [*] --> 新入图: autoMake 把词写进图
    新入图 --> 衰减中: memory_strength = 0.0<br/>last_reviewed_at 为空
    衰减中 --> 刚复习: POST /api/review<br/>置 1.0 · 记录当前时间
    刚复习 --> 衰减中: 时间流逝<br/>e^(-Δt / 7天)
    衰减中 --> 衰减中: 越久越暗<br/>rank 分数越高
    note right of 新入图
        从未复习 = 0.0
        所以 score = weight_norm
        高频核心词天然排最前
    end note
    note right of 衰减中
        半衰期 7 天
        7 天后 ≈ 0.37
        14 天后 ≈ 0.14
    end note
```

### 6.2 前端复习循环

```mermaid
flowchart TB
    A(["点击 Word 节点"]) --> B["openQuiz<br/>选中 + 居中 + 邻接高亮"]
    B --> C["面板显示中文释义<br/>要求填英文"]
    C --> D["面板绑定 pan zoom 事件<br/>跟随节点移动"]
    D --> E{"用户操作"}

    E -->|"填对"| F["POST /api/review"]
    E -->|"点 显示正确答案"| F
    E -->|"按 Esc"| Z["closeQuiz<br/>state.cy 空值守卫"]
    E -->|"点面板上的 +"| G["打开增词弹窗<br/>焦点词 = 当前词"]

    F --> H["memory_strength 置 1.0<br/>节点变亮"]
    H --> I{"响应里有 next？"}
    I -->|"有"| J["自动跳到下一个待复习词<br/>openQuiz(next)"]
    I -->|"没有"| Z
    J --> C

    G --> K["见第 7 节 增词弹窗流程"]
```

**闭环**：答对 → 变亮 → 自动跳下一题，不用手动找词。
下一题是 `rank` 第一位，即"最重要且最快忘光"的那个。

---

## 7. 前端首页流程（冷启动建图）

```mermaid
flowchart TB
    A(["打开 /"]) --> B["GET /api/categories<br/>渲染笔记列表"]
    B --> C{"用户做什么"}

    C -->|"点已有笔记"| D["跳转 /graph?category=..."]
    C -->|"新建笔记"| E["输入分类名 + 描述"]

    E --> F["点 生成候选单词"]
    F --> G["POST /api/candidate-words<br/>只调 LLM · 不写库"]
    G --> H{"LLM 返回了词？"}
    H -->|"没有"| I["提示重试"]
    H -->|"有"| J["渲染勾选列表<br/>半自动"]

    J --> K["用户勾选种子"]
    K --> L["点 生成图"]
    L --> M["POST /api/automake<br/>带 seeds · 手动模式"]
    M --> N["刷新笔记列表<br/>GET /api/categories"]
    N --> D

    style G fill:#4a3728,color:#fff
    style M fill:#4a3728,color:#fff
```

**首页没有滑块**——冷启动时图里没词，`select_seeds` 直接返回空、回退 LLM，
滑块拖到哪都不起作用。放上去只会误导。

---

## 8. 图页面增词弹窗流程

两个「+」共用同一个弹窗，区别只在带不带 `focus_word`：

```mermaid
flowchart TB
    A1(["右上角 + <br/>整图增词"]) --> M
    A2(["单词面板的 + <br/>焦点词模式"]) --> M["打开 grow-modal<br/>切到表单视图"]

    M --> S["滑块<br/>例句对高权重单词的依赖程度<br/>左=少依赖挑生词 / 右=多依赖挑核心词"]
    S --> D{"oninput"}
    D -->|"防抖 250ms"| P["GET /api/seeds<br/>category intensity k focus"]
    P --> PV["实时预览<br/>这一轮会选中哪些种子及其度数"]
    PV --> S

    S --> OK["点确认"]
    OK --> AM["POST /api/automake<br/>seeds 为空 + intensity · 焦点词模式再带 focus_word"]
    AM --> R["切到结果视图<br/>本批 N 条例句 · M 个新单词"]

    R --> RN{"M 大于 0？"}
    RN -->|"是"| CHIP["新词渲染成 chip<br/>点击直接在图上定位"]
    RN -->|"否"| TIP["提示：把滑块往左拖更容易出生词"]

    CHIP --> NEXT{"下一步"}
    TIP --> NEXT
    NEXT -->|"点 再来一轮"| BACK["回到表单视图<br/>保持同一焦点词"]
    NEXT -->|"点 完成"| CLOSE["关闭弹窗"]
    BACK --> S

    CLOSE --> RG["reloadGraph<br/>销毁并重建 Cytoscape 实例"]
    CHIP --> RG

    style AM fill:#4a3728,color:#fff
    style P fill:#1e3a2f,color:#fff
```

### 两个约束

1. **整图视图（URL 无 `?category=`）下两个「+」都隐藏**——写库必须落到某个 Category，
   分类不明确就没法写。
2. **`reloadGraph()` 期间 `state.cy` 会短暂为 `null`**，所以 `closeQuiz`、
   `closeSentencePanel`、面板跟随回调都做了空值守卫，否则重建过程中触发这些回调会报错。

---

## 9. 搜索框流程

```mermaid
flowchart TB
    A(["在搜索框输入"]) --> B["三级排序候选"]
    B --> B1["① 英文前缀匹配"]
    B --> B2["② 英文包含"]
    B --> B3["③ 中文释义包含"]
    B1 --> C["合并去重 · 最多 8 条"]
    B2 --> C
    B3 --> C

    C --> D{"键盘 / 鼠标"}
    D -->|"↑ ↓"| E["切换高亮候选"]
    D -->|"回车 / 点击"| F["openQuiz(node)"]
    D -->|"框内按 Esc"| G["只收起候选列表<br/>stopPropagation<br/>防止冒泡到全局 Esc"]

    E --> D
    F --> H["选中 + 居中 + 邻接高亮<br/>+ 打开填空面板"]
```

框内 Esc 必须 `stopPropagation()`：不然会冒泡到全局 Esc 处理器，
把刚打开的填空面板一起关掉。

---

## 10. 布局切换流程

```mermaid
flowchart TB
    A(["右上角单选 layout-bar"]) --> B{"选了哪个"}

    B -->|"力导向 · 默认"| C["cose 布局<br/>物理模拟"]
    B -->|"按记忆度"| D["concentric<br/>值 = round(memory_strength × 10)<br/>11 档"]
    B -->|"按权重"| E["concentric<br/>值 = 后端给的 weight<br/>缺失时退回 node.degree()"]

    D --> F["Category 恒返回 100<br/>钉在最中心"]
    E --> F
    F --> G["levelWidth 恒返回 1<br/>一档一圈"]
    G --> H["值越大 → 越靠圆心"]

    C --> I["重新 run 布局"]
    H --> I
```

### 两个必须记住的点

- **`concentric` 回调返回值越大，排得越靠圆心**（不是越靠外）。
  所以"记得越牢越靠中心"要用 `memory_strength × 10`，不能取反。
- **`levelWidth: () => 1` 不能省**。默认的 `levelWidth` 会把相近的值归成一档，
  结果所有节点挤成一两圈，完全看不出层次。

已用 headless Cytoscape 实测验证过：权重模式下 `exam`(12) 距圆心 23px、
`critical`(7) 46px、`anxiety`(2) 69px；记忆度模式下顺序相反。

---

## 11. 测试流程

```mermaid
flowchart LR
    A(["python -m pytest"]) --> B["构造 FakeGraphDB<br/>内存字典模拟 Neo4j"]
    B --> C["构造 FakeLLM<br/>返回固定例句和释义"]
    C --> D["跑被测服务层函数"]
    D --> E["断言写入的节点 / 边 / 返回值"]

    B -.->|"按查询字符串<br/>精确匹配分发"| F["app/models/graph.py<br/>的 Cypher 常量"]

    style F fill:#2d3748,color:#fff
```

**加新 Cypher 常量时的注意事项**：`FakeGraphDB` 是靠**查询字符串精确匹配**来分发的。
往 `models/graph.py` 加了新常量、而 Fake 里没加对应分支时，
`run()` 会**静默返回空列表**而不是报错——测试可能假绿。
所以新增查询后，要么在 Fake 里补分支，要么确认没有测试路径会走到它。
