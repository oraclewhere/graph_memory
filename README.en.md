# graph_memory - English Vocabulary Memory Graph

An intelligent vocabulary memorization system built on a graph structure. The LLM auto-generates example sentences, and words naturally associate within sentences, forming two mutually reinforcing knowledge graphs.

[English](README.en.md) | [中文](README.md)

## Core Features

**Self-growing loop**: Seed words → LLM generates sentences → new words from sentences enter the graph → loop expansion

**Dual graph structure**:
- **Sentence graph**: word ↔ sentence ↔ category
- **Word graph**: words linked through shared affixes (prefix/suffix)

**Three learning modes**:
- **Explore mode**: visualize the knowledge graph, click for definitions, with search and multiple layout options
- **Review mode**: letter-by-letter fill-in review, intelligently ordered by memory strength and weight
- **Memory mode**: letter-by-letter reveal → flip the card for the definition → placement quiz (match definition / fill in the sentence / select word by definition)

**Smart algorithms**:
- Convergence strength control: a slider adjusts the seed selection strategy, balancing "consolidate the core" vs "expand new words"
- Ebbinghaus forgetting curve: memory strength decays in real time, forgotten words are prioritized for review
- Degree-centrality weighting: word importance assessed through six degrees of separation theory

**Multi-user isolation**: each user's graph data is fully independent, with support for custom LLM API configuration

## Tech Stack

- **Backend**: Python 3.10+ / FastAPI
- **Graph storage**: Neo4j (Cypher queries)
- **User data**: MySQL + SQLAlchemy + JWT authentication
- **Frontend**: vanilla HTML/CSS/JS + Cytoscape.js visualization
- **LLM**: OpenAI-compatible API (supports both global and per-user configuration)

## Quick Start

```bash
# 1. Install dependencies (requires Python 3.10+)
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Start the databases (Neo4j + MySQL)
docker compose up -d

# 3. Configure the LLM: copy the template and fill in api_base / api_key / model
cp config/llm.example.yaml config/llm.yaml

# 4. Quickly verify autoMake (optional)
python -m app.cli

# 5. Start the web service
uvicorn app.main:app --reload
```

Visit http://localhost:8000 to get started.

## Screenshot

![graph_memory screenshot](docs/images/image.png)

## Configuration

### `config/llm.yaml` — LLM configuration

The global default LLM API configuration. Users can also configure their own API on the profile page.

```yaml
api_base: "https://api.openai.com/v1"  # OpenAI-compatible endpoint
api_key: "sk-xxx"                       # API key
model: "gpt-4o-mini"                    # Model name
timeout: 60                             # Request timeout (seconds)
```

Works with any OpenAI-compatible endpoint (DeepSeek, Qwen, etc.).

### `config/affixes.yaml` — Affix list

Defines English derivational affixes (prefix/suffix) used to build `SHARES_PREFIX` / `SHARES_SUFFIX` edges between words.

- Each affix contains: `affix` (the affix itself), `meaning_cn` (Chinese meaning), `meaning_en` (English meaning)
- Matching method: simple string matching (`startswith` / `endswith`)
- Only derivational affixes are included; inflectional affixes (`-ing`/`-ed`, etc.) are excluded since they produce noisy edges

You can extend the affix list to strengthen word associations.

## Documentation

Detailed docs live in the [`docs/`](docs/) directory:

| Doc | Content |
|------|----------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layered architecture, module dependencies, Neo4j ER model, frontend structure |
| [DATAFLOW.md](docs/DATAFLOW.md) | Global data flow, auth flow, autoMake write path, four read paths, self-growing loop |
| [FLOWCHART.md](docs/FLOWCHART.md) | Login flow, full autoMake flow, seed selection decision tree, review loop |
| [README.md](docs/README.md) | Documentation index |

## Project Structure

```
graph_memory/
├── app/
│   ├── api/           # FastAPI routes (auth, user, admin, business APIs)
│   ├── models/        # Data models (Neo4j graph model, MySQL user model)
│   ├── services/      # Business logic (autoMake, LLM, memory strength, weight, graph query)
│   ├── static/        # Frontend pages (login, notes list, graph view, profile)
│   ├── config.py      # Configuration loading
│   ├── db.py          # Neo4j connection
│   └── main.py        # FastAPI entry point
├── config/
│   ├── llm.yaml       # LLM configuration (create it yourself)
│   └── affixes.yaml   # Affix list
├── docs/              # Project documentation
├── tests/             # pytest tests
└── docker-compose.yml # Neo4j + MySQL
```

## License

MIT