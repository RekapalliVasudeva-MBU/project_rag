# AetherMind — project_rag (Web RAG Server)

> A hosted web RAG backend for AetherMind. The static landing page is served separately,
> while the API ingests GitHub-hosted PDFs and answers questions with OpenRouter.

The **project_rag** repo contains the cloud-ready RAG backend and website assets for AetherMind.
It is designed to run on a Python host such as Render, while the frontend can be served from
GitHub Pages or another static host.

It is one half of the **AetherMind** suite:

| Repo | What it is |
|------|------------|
| **`project_rag`** (this repo) | The **web RAG server** — backend + static UI assets. |
| [`aether-desktop`](https://github.com/RekapalliVasudeva-MBU/aether-desktop) | The **desktop companion app** — downloaded from GitHub. |

## What it does

- Hybrid RAG: **Docling** PDF parsing → chunks → **BM25 + vector** retrieval → **reranker** → **RRF** fusion.
- Cloud answer generation using **OpenRouter**.
- Supports GitHub-backed PDF ingestion via `RAG_PDF_SOURCE=github`.
- Serves static UI assets, chat endpoints, and app download redirects.
- Optional PostgreSQL visitor logging.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY, RAG_GITHUB_REPO, RAG_GITHUB_PATH
uvicorn server:app --host 0.0.0.0 --port 8000
```

## Project layout

```
server.py            # FastAPI backend for the chat API and static UI assets
web_ui/              # static website pages (index.html, knowledge.html, aether-docs.html)
render.yaml          # Render deployment configuration
requirements.txt     # runtime dependencies for the backend
```


## Related

- Desktop app: [`aether-desktop`](https://github.com/<your-org>/aether-desktop)
- Desktop docs: `/aether-docs` on the live site

---

© AetherMind — a 2-in-1 project: a hosted web RAG server and a self-hosted desktop agent.
