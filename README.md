# AetherMind — project_rag (Web RAG Server)

> **🌐 Live site:** [https://marshy-ancient-rebuild.ngrok-free.dev](https://marshy-ancient-rebuild.ngrok-free.dev)
> — chat with your PDFs, **download the desktop app**, and read the docs.
> Desktop app download: **[GitHub Releases](https://github.com/RekapalliVasudeva-MBU/aether-desktop/releases/download/v1.0.0/Aether-Setup.exe)** (fast CDN) ·
> Desktop docs: **[/aether-docs](https://marshy-ancient-rebuild.ngrok-free.dev/aether-docs)**.

The **hosted web RAG server** for the AetherMind project — a FastAPI app that lets you chat with
your own PDFs through a hybrid retrieval pipeline, served on a public website.

It is one half of the **AetherMind** 2-in-1 suite:

| Repo | What it is |
|------|------------|
| **`project_rag`** (this repo) | The **web RAG server** — chat with your PDFs in a browser. |
| [`aether-desktop`](https://github.com/<your-org>/aether-desktop) | The **desktop companion app** — the same engine packaged as a Windows `.exe`. |

Both share the same hybrid RAG core; this repo runs it in the cloud and also **hosts the website
and the desktop-app download + documentation**.

## What it does

- Hybrid RAG: **Docling** PDF parsing → chunks → **BM25 + vector** retrieval → **reranker** → **RRF** fusion.
- Chat UI (Chat / Shelf / Settings tabs) with your own provider key or a local Ollama model.
- Serves the public website (`/`) and the **desktop app download** (`/download/aether`) +
  **desktop docs** (`/aether-docs`).
- PostgreSQL-backed visitor logging (optional).

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env        # add your provider key / ngrok token
python server.py            # http://127.0.0.1:8000
```

The server auto-opens an ngrok tunnel to a static domain when `NGROK_AUTHTOKEN` is set.

## Project layout

```
server.py            # FastAPI app + ngrok tunnel + download routes
web_ui/              # website (index.html, knowledge.html, aether-docs.html)
dist/                # built installers (ProjectRAG-Setup.exe, Aether-Setup.exe) — not committed
```

## Related

- Desktop app: [`aether-desktop`](https://github.com/<your-org>/aether-desktop)
- Desktop docs: `/aether-docs` on the live site

---

© AetherMind — a 2-in-1 project: a hosted web RAG server and a self-hosted desktop agent.
