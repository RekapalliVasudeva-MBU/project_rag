# RAG System (docling pipeline)

Retrieval-Augmented Generation system built from First_Rag.ipynb.

## Pipeline (matches the notebook exactly)
1. **PyMuPDF** — splits large PDFs into 8-page chunks (cached on disk).
2. **docling `DocumentConverter`** — converts each PDF -> markdown (layout + OCR).
3. **docling `HybridChunker`** — structural chunking that preserves H1/H2
   `headings` metadata (`merge_peers=True`, `max_tokens=512`).
4. **ChromaDB** — stores chunk text + `headings` in `docling_knowledge_base`.
5. **Ollama (local)** — answers questions from retrieved context.

GPU: docling uses `AcceleratorDevice.CUDA` automatically when a GPU is
available; otherwise falls back to CPU.

## Usage
```
cd C:\Users\valte\project_rag
python main.py
```
First run builds the vector DB (slow on CPU — docling runs OCR). Subsequent
runs: the DB is persisted in `rag_vector_db/`, and the 8-page PDF chunks are
cached in `rag_pdfs/temp_split_chunks/`, so re-runs are much faster.

## Dependencies
See `setup.py` (`docling`, `PyMuPDF`, `torch`, `transformers`,
`sentence-transformers`, `chromadb`, `ollama`, `fastapi`, `uvicorn`,
`pyngrok`, `psycopg2-binary`, ...).
Install: `pip install -e .`

---

# 🌐 Web Deployment (your laptop = the server)

`server.py` turns this RAG system into a public website backed by YOUR local
Ollama GPU model. Online visitors chat through the `web_ui/` chat interface;
their requests are queued and answered **one at a time** (your 8 GB VRAM can't
serve many users at once).

## What it does
- Serves the premium chat UI (`web_ui/index.html`) at `/`
- `/api/chat` — POST a question, streams the answer token-by-token over SSE
- Strict **serial queue**: one answer at a time, others wait their turn
- `/download/desktop` — serves `project_rag_hybrid.zip` (the self-hosted app)
- `/api/waitlist` — stores download-signup emails in PostgreSQL
- Logs every visit/question to PostgreSQL **only while your laptop is on**
- ngrok tunnel (optional) gives a public HTTPS URL — set your token in
  `server_config.json` (`ngrok_auth_token` + `ngrok_static_domain`)

## Run it
```bash
cd C:\Users\valte\project_rag
python server.py
```
Then open `http://127.0.0.1:8000/`. For public access, add your ngrok
token/domain to `server_config.json` (or set `NGROK_AUTH_TOKEN` /
`NGROK_DOMAIN` env vars) and restart.

## Postgres (visitor + waitlist storage)
- DB `rag_site` on `localhost:5432` (creds in `server_config.json`).
- Tables `visitor_logs` and `waitlist` are created automatically on connect.
- If Postgres is down, the site still works — visitor logging is just skipped.

## Build the downloadable desktop app zip
```bash
python build_desktop_zip.py        # -> dist/project_rag_hybrid.zip
```
The zip ships `project_rag_hybrid` code + a blank `rag_settings.json`
(NO API key) and excludes `rag_vector_db/` (your private indexed data).
Downloaders run it entirely on their own hardware.

## Privacy model
- Visitors only chat with YOUR local model against YOUR knowledge base.
- The downloadable hybrid app contains NONE of your data or keys.
- A downloader's `rag_vector_db/` and `rag_settings.json` are created fresh
  on their machine — they never see yours.

