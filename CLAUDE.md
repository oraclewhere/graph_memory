# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

graph_memory 是一个英文单词记忆图服务。核心是 `autoMake` 自生长循环：**种子单词 → LLM 生成例句 → 例句中的新单词入图 → 新单词再作为种子**，如此反复，逐步长出两张互相促进的图。

- **例句图**：单词 ↔ 例句 ↔ 分类
- **单词图**：单词之间通过共享英文前缀/后缀互相关联

## 设计文档（`docs/`）

本文件是速查手册；成体系的图文说明在 `docs/`，改动架构时记得同步：

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 分层架构图、模块依赖图、Neo4j 数据模型 ER 图、前端结构、测试架构
- [`docs/DATAFLOW.md`](docs/DATAFLOW.md) — 全局数据流、autoMake 写路径、四条读路径、自生长闭环
- [`docs/FLOWCHART.md`](docs/FLOWCHART.md) — autoMake 完整流程、种子选择决策树、强度采样、复习循环、前端交互流程
- [`docs/README.md`](docs/README.md) — 文档索引

## 技术栈

- Python 3.10+，FastAPI（Web 服务）
- Neo4j（图存储，通过 `docker compose` 启动）
- 可配置 LLM（OpenAI 兼容接口，任意 `base_url` / `api_key` / `model`）
- pytest（测试）

## 快速开始

```bash
# 安装依赖（注意用 python3.10，见下方「环境注意事项」）
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 启动 Neo4j（账号 neo4j / password，见 docker-compose.yml）
docker compose up -d

# 填入 LLM 配置：编辑 config/llm.yaml 的 api_base / api_key / model

# 终端快速验证 autoMake（交互式）
python -m app.cli

# 启动 Web 服务（浏览器打开 http://localhost:8000 进入笔记列表首页，生成图后点击笔记跳转到 /graph 查看子图）
uvicorn app.main:app --reload
```

## 环境注意事项

- **Python 版本**：系统默认 `python` 是 3.7（anaconda base），不满足要求，必须用 `python3.10`（`/usr/bin/python3.10`）。
- **pip 源**：本环境默认源 `pypi.org` 被墙，需加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`（阿里镜像也可用）。
- **venv**：`python3.10 -m venv` 可能因缺少 `ensurepip` 失败，需先 `apt install python3.10-venv`。装不上时可直接用系统 `python3.10 -m pip install`（本环境已用此方式装好依赖）。

- **git 管理**： 每次对话后修改的代码需要提交到git仓库，并合并到当前分支
## 测试

```bash
python -m pytest                              # 全部
python -m pytest -v                           # 详细输出
python -m pytest tests/test_automake.py       # 单个文件
python -m pytest -k <name>                    # 单个用例
```

测试不依赖真实 Neo4j / LLM API：用 `tests/test_automake.py` 里的 `FakeGraphDB`（内存模拟 Neo4j，精确匹配 `app/models/graph.py` 的查询常量）和 `FakeLLM`（返回固定结果）。

## 架构总览

### autoMake 核心循环（`app/services/automake.py`）

一轮循环的流程：

1. 确保分类节点存在（`ensure_category`）。
2. 确定种子单词，三条路径：
   - 调用方传入 `seeds`（前端手动勾选）；
   - `pick_seeds(category, intensity, k, focus)` **按收敛强度从图里自动选**（自生长主路径，见下「收敛强度」；`focus` 非空时该词必定入选）；
   - 图里该分类还没有词（冷启动）时，`pick_seeds` 回退到 `llm.generate_top_words(requirement, n)`。
3. 确保种子单词入图（`Word` 节点 + `BELONGS_TO` 边）。
4. `llm.generate_sentences(seeds, category, n)` 生成 n 条该分类例句。
5. LLM 返回结构化结果（例句 + 中文翻译 + 句内实词的「原形/词性/中英释义」），把其中不在图中的实词（原形）作为新单词入图。词形还原由 LLM 完成（asserting → assert），避免屈折形式拆成多个节点。
6. 建例句边：`Sentence` 节点（含翻译）+ `BELONGS_TO` + 对句中每个实词建 `CONTAINS` 边。
7. 对新单词按词缀清单建 `SHARES_PREFIX` / `SHARES_SUFFIX` 边。
8. 返回本轮 `new_words`（作为下一轮候选种子，实现自生长）。

### 服务层模块（`app/services/`）

- **`automake.py`** — 核心自生长引擎（见上）。
- **`weight.py`** — 单词重要度权重。基于六度空间理论：一个单词关联的节点越多越核心，记忆收益越高。**实时计算**（不存节点属性），v1 用度中心性（`ALL_WORD_DEGREES` 查询），**算法后续可升级 GDS PageRank**。`compute_weights()` 返回度中心性，`rank_words()` 结合记忆度给出推送顺序（复习侧），`select_seeds()` 按收敛强度选下一轮种子（生成侧，见下）。
- **`memory.py`** — 记忆度（艾宾浩斯遗忘曲线）。`memory_strength = e^(-Δt / half_life)`，`half_life` 默认 7 天。单词**入图时 `memory_strength = 0.0`（从未复习）**，`POST /api/review` 复习成功后置 `1.0` 并写入 `last_reviewed_at = 现在`，之后随时间指数衰减。
- **`graph_query.py`** — 图结构导出。`get_graph(gdb, category=None)` 把图导出为 `{nodes, edges}`（供前端可视化），指定 `category` 时只导出该分类子图。Word 节点带实时计算的记忆度 + `weight`（度中心性，与 `weight.py` 同一个 `ALL_WORD_DEGREES` 查询，保证前端排布和推送排序口径一致）；Sentence 节点的 `memory_strength` = 所含词记忆度的均值、`weight` = 所含实词数，并带 `words`（句内实词原形列表，供例句弹窗点击跳转）。
- **`review.py`** — 关联审查（**预留**，审查例句质量 / 新词是否该入图，逻辑待定）。
- **`rumination.py`** — 反刍（**预留**，对生成结果二次修改，与艾宾浩斯复习无关，逻辑待定）。

### 推送顺序（复习排序）

`weight.rank_words(gdb)`：度中心性先归一化到 0~1（除以最大度），记忆度本就是 0~1，`score = weight_norm × (1 - memory_strength)`（重要度 × 遗忘比例），降序 = 最该先复习的词。已暴露为 `GET /api/rank`。

### 收敛强度（自生长驱动）

`weight.select_seeds(gdb, category, intensity, k)`：种子不再靠人肉勾选，而是**按滑块强度从图里按权重取样**。

- `intensity ∈ [0,1]`（超界自动 clamp），把分类内的度中心性归一化到 0~1 后，取 `|weight_norm - intensity|` 最小的 k 个词——**滑块停在权重谱哪个位置，就从哪取种子**。
- **强度高 = 收敛**：取核心高频词，例句围着老词转，句中实词多半已在图里，新词少 → 图变密。
- **强度低 = 扩张**：取边缘低度词（多是上一轮刚入图、只挂一条例句的新词），围着它们造句能拽出大量生词 → 图长大。
- **闭环关键**：`run()` 产出的 `new_words` 入图后度最低，低强度下会自动被选成下一轮种子，**无需调用方手动回灌**。
- 分类在图中无词（冷启动）时返回 `[]`，由 `AutoMake.pick_seeds()` 回退 LLM。
- 同距离时按「高权重优先 → 字母序」兜底，保证结果稳定可测。

**焦点词模式**（`pick_seeds(..., focus="reform")`，图页面点单词上的「+」）：该词**必定**作为种子且排第一，其余 k-1 个「陪衬词」仍按强度取样（`select_seeds(exclude={focus})`）——强度高则陪核心高频词，强度低则陪边缘生词。焦点词本身就是合法种子，所以这条路**不走 LLM 冷启动**。`exclude` 的词不参与取样但仍参与归一化基准，避免「核心度」标尺漂移。

**滑块该放哪**：强度只在图已经长出来之后才有意义——冷启动时 `select_seeds` 返回 `[]` 直接回退 LLM，滑块不起作用。所以滑块在**图页面**，不在首页。

### 查询接口（`app/api/routes.py`）

- `GET /api/graph?category=` — 返回图 `{nodes, edges}`，Word 节点带实时记忆度和 `weight`（度中心性，供前端同心圆排布）；指定 `category` 时只返回该分类子图。
- `GET /api/categories` — 返回所有分类及统计 `{categories: [{name, description, word_count, sentence_count}]}`（笔记列表用）。
- `POST /api/candidate-words` — body `{category, n}`：让 LLM 生成候选种子单词（只调 LLM、不写库），返回 `{words}`，供半自动勾选。
- `GET /api/seeds?category=&intensity=&k=&focus=` — 预览按收敛强度选出的种子（**只读图、不调 LLM、不写库**），返回 `{words: [{text, weight, weight_norm, distance}], intensity, focus, cold_start}`，供图页面滑块即时反馈。带 `focus` 时返回的是**陪衬词**（焦点词自身已从取样中排除，由前端展示）。
- `POST /api/automake` — body `{category, seeds, n_sentences, description, intensity, n_seeds, focus_word}`：执行一轮 autoMake 并写库。三种模式：**`seeds` 非空 = 用勾选的种子**（首页新建笔记）；**`seeds` 为空 = 按 `intensity` 自动选种子**（图页面右上角「+」，图空则 LLM 冷启动）；**再带 `focus_word` = 焦点词模式**（图页面单词上的「+」）。返回 `{ok, auto_seeds, intensity, focus_word, category, seeds, sentences, new_words}`。
- `GET /api/rank?limit=N` — 返回推送复习顺序（见上）。
- `POST /api/review` — body `{"word": "..."}`：复习成功后重置该词记忆度，返回 `{ok, word, memory_strength, next}`（`next` 是下一个待复习词，即 rank 第一位）。
- `GET /api/health` — 健康检查。

### 前端（`app/static/`）

两个单文件页面，均复用同一套暗色设计变量，用 Cytoscape.js（本地 `/static/cytoscape.min.js`，已下载进仓库）渲染力导向图：

**职责划分：首页只管「从零建一张图」（冷启动），图页面才管「让图继续长」（增词）。**

- **`notes.html`（首页 `/`）** — 笔记列表 + 新建笔记（冷启动，无滑块）。输入分类 → 「生成候选单词」调 `POST /api/candidate-words` 渲染勾选列表（半自动）→ 勾选后「生成图」调 `POST /api/automake`（带 `seeds`）→ 刷新笔记列表（`GET /api/categories`，一个分类一条）。点击笔记跳转 `/graph?category=...`。
- **`index.html`（图视图 `/graph`）** — 读取 `?category=` 参数只显示该分类子图（无参数则整图）。交互：
  - **节点亮度 = 记忆度**：Word 节点用单一蓝色从暗（记忆度低）到亮（记忆度高），Category 橙色、Sentence 灰色。
  - **点击单词节点 → 中文释义填空英文**：面板跟随节点移动（绑定 `pan zoom`），填对或「显示正确答案」都调 `POST /api/review` 更新记忆度、节点变亮，并自动跳到 rank 返回的下一个待复习词。
  - **点击例句节点 → 弹窗**：显示英文例句 + 中文翻译 + 句内实词的「词性/中文释义/英文释义」，句中单词可点击跳转到对应 Word 节点；Esc 退出弹窗。
  - **顶部中间搜索框**：按英文前缀 → 英文包含 → 中文释义包含三级排序，最多 8 条候选，`↑↓` 切换、回车/点击选中 → 调 `openQuiz()` 定位（选中 + 居中 + 邻接高亮 + 打开填空面板）。框内 Esc 只收候选、`stopPropagation` 防止冒泡到全局 Esc 连带关掉填空面板。
  - **排布方式（右上角单选）**：`力导向`（cose，默认）/ `按记忆度` / `按权重`。后两者用 Cytoscape 的 `concentric` 布局，**回调返回值越大排得越靠圆心**：记忆度 ×10 取整分 11 档（记得越牢越靠中心），权重取后端给的度中心性（缺失时退回 `node.degree()`），Category 恒返回 100 钉在最中心。`levelWidth: () => 1` 保证一档一圈，否则会挤成一两圈。
  - **右上角「＋」→ 增词弹窗**：提示「是否增加新的单词？」，滑块 = **例句对高权重单词的依赖程度**（左=少依赖挑生词 / 右=多依赖挑核心词），`oninput` 防抖 250ms 调 `GET /api/seeds` 实时预览会选中哪些种子及其度数；确认后调 `POST /api/automake`（`seeds: []` + `intensity`），完成后 `reloadGraph()` 就地重建 Cytoscape 实例。
  - **生成结果面板**：生成完不再直接关窗，弹窗切到结果视图显示**本批例句数 + 新增单词数**，新词渲染成 chip，点击直接在图上定位；「再来一轮」回到表单（保持同一焦点词），「完成」关闭。没长出新词时给出提示（把滑块往左拖更容易出生词）。
  - 本页**没有通用 `.hidden` 规则**（quiz/sentence 面板用 opacity 做淡出），新增元素要显隐必须按 id 补 `#xxx.hidden { display:none }`，否则 `classList.toggle('hidden')` 静默失效。
  - **单词面板上的「＋」→ 同一弹窗的焦点词模式**：围绕当前单词造句，`focus_word` 带上该词，滑块此时控制陪衬词取核心词还是生词。
  - 两个「＋」都需要明确分类（写库要落到某个 Category），**整图视图（无 `?category=`）下隐藏**。
  - **邻接高亮**：点击节点后其邻接节点高亮、其余变暗。
  - `reloadGraph()` 期间 `state.cy` 会短暂为 `null`，`closeQuiz` / `closeSentencePanel` / 面板跟随回调都做了空值守卫。
- 由 `main.py` 托管：`/` 返回 `notes.html`，`/graph` 返回 `index.html`，`/static/*` 服务静态资源，`/api/*` 走路由。

### 数据流向

`cli.py` / `main.py`（入口） → `services/automake.py`（编排） → `services/llm.py`（LLM）+ `db.py`（Neo4j）。所有 Cypher 查询集中在 `app/models/graph.py` 常量里，`db.py` 的 `GraphDB.run()` 是唯一的写库入口。

## Neo4j 数据模型（`app/models/graph.py`）

**节点：**
- `(:Category {name, description})` — 分类，可多个，`name` 唯一
- `(:Word {text, pos, definition_cn, definition_en, frequency, memory_strength, last_reviewed_at})` — 英文单词，`text` 唯一，`definition_cn` 中文释义、`definition_en` 英文定义、`frequency` 出现次数、`memory_strength` 记忆度（0~1，实时计算）、`last_reviewed_at` 上次复习时间（艾宾浩斯衰减锚点）
- `(:Sentence {text, translation, created_at})` — 例句，`translation` 中文翻译

**边：**
- `(Word)-[:BELONGS_TO]->(Category)`
- `(Sentence)-[:BELONGS_TO]->(Category)`
- `(Sentence)-[:CONTAINS]->(Word)`（建边时递增 `Word.frequency`）
- `(Word)-[:SHARES_PREFIX {affix}]->(Word)` / `(Word)-[:SHARES_SUFFIX {affix}]->(Word)`

**约束**：`Word.text`、`Category.name` 唯一，由 `db.py:init_constraints()` 幂等创建。

## 配置

- `config/llm.yaml` — LLM 配置（`api_base` / `api_key` / `model` / `timeout`），含密钥，已在 `.gitignore` 忽略；模板见 `config/llm.example.yaml`。加载逻辑在 `app/config.py`。
- `config/affixes.yaml` — 英文词缀清单（前缀/后缀），控制单词图的前后缀关联。**v1 是简单 `startswith`/`endswith` 字符串匹配，会产生噪音边**（如 `un` 会匹配 `under`），仅收录派生词缀、不收屈折词缀（`-ing`/`-ed`）。
