"""
FastAPI production server for project_rag (LUMINA / "AetherMind" local RAG site).

Your laptop is the server. Online users reach the premium chat UI through this
backend, which:
  - retrieves context from the docling-built ChromaDB (rag_vector_db/)
  - generates answers with your LOCAL Ollama model on the RTX 5070 (keep_alive -1)
  - streams tokens back over SSE (text/event-stream) for a typewriter effect
  - runs requests ONE AT A TIME (strict serial queue) so one user's long answer
    does not get interleaved with another's (per spec: 1 user/session, queue the rest)
  - logs visits + questions to PostgreSQL (only when your laptop is on)
  - serves the premium landing + chat UI
  - serves the downloadable "desktop app" (project_rag_hybrid) zip
  - exposes a waitlist signup endpoint (stored in Postgres)

Tunnel: ngrok (public URL) is opened in the lifespan hook (ChatGPT's plan), using
your auth token + free static domain from server_config.json (gitignored / private).

Run:  python server.py
"""

import os
import sys
import json
import time
import asyncio
import uuid
from pathlib import Path
from collections import deque

# --- UTF-8 stdout/stderr shim (Windows) ---
# The Startup .cmd launches this under the system console codepage (often
# cp1252). Python then crashes on the emoji prints (🚀) BEFORE binding the
# port, so the site dies after a reboot. Force UTF-8 to survive reboots.
if sys.stdout and sys.stdout.encoding and "utf" not in sys.stdout.encoding.lower():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and sys.stderr.encoding and "utf" not in sys.stderr.encoding.lower():
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import chromadb
from chromadb.utils import embedding_functions
import ollama
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# --- minimal OpenTelemetry tracing (no external collector: prints to console) ---
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

_tp = TracerProvider()
_tp.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(_tp)
tracer = trace.get_tracer("aethermind.rag")

# --- local RAG backend (docling pipeline lives in main.py) ---
import main as rag

_PROJECT_DIR_FOR_KEY = Path(__file__).parent  # noqa: E402


def _hermes_openrouter_key() -> str:
    """Read the OpenRouter key from the hermes .env (user authorized reuse)."""
    import os as _os
    for env_path in (
        _os.environ.get("LOCALAPPDATA", ""),
        _os.environ.get("APPDATA", ""),
    ):
        p = Path(env_path) / "hermes" / ".env" if env_path else None
        if p and p.exists():
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("OPENROUTER_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    home_env = Path.home() / ".hermes" / ".env"
    if home_env.exists():
        for line in home_env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return ""

PROJECT_DIR = Path(__file__).parent
UI_DIR = PROJECT_DIR / "web_ui"          # premium UI (static HTML) served to visitors
HYBRID_DIR = PROJECT_DIR.parent / "project_rag_hybrid"
CONFIG_PATH = PROJECT_DIR / "server_config.json"
DASHBOARD_LOG_DIR = PROJECT_DIR / "dashboard_log"   # local dashboard snapshots (JSON)

# ---------------------------------------------------------------------------
# Config (private: ngrok token/domain). NEVER commit this file.
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "ngrok_auth_token": "",          # paste your ngrok token (or set NGROK_AUTH_TOKEN env)
    "ngrok_static_domain": "",       # e.g. "upward-glowing-mutt.ngrok-free.app" (or set NGROK_DOMAIN env)
    # --- LLM (OpenRouter, cloud — no local GPU required) ---
    "openrouter_api_key": "",        # leave empty to auto-read from hermes .env / OPENROUTER_API_KEY env
    "openrouter_model": "openrouter/free",
    "host": "127.0.0.1",
    "port": 8000,
    "ollama_model": "richardyoung/qwythos-9b-abliterated:Q4_K_M",
    "public_base_url": "",           # auto-filled from ngrok at startup; used in download links
    "postgres": {
        "dsn": "dbname=rag_site user=postgres password=postgres host=127.0.0.1 port=5432"
    },
    "allow_download": True,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.load(open(CONFIG_PATH, "r", encoding="utf-8")))
        except Exception:
            pass
    # env overrides
    cfg["ngrok_auth_token"] = os.environ.get("NGROK_AUTH_TOKEN", cfg["ngrok_auth_token"])
    cfg["ngrok_static_domain"] = os.environ.get("NGROK_DOMAIN", cfg["ngrok_static_domain"])
    cfg["postgres"]["dsn"] = os.environ.get("RAG_PG_DSN", cfg["postgres"]["dsn"])
    return cfg


CONFIG = load_config()

# ---------------------------------------------------------------------------
# ChromaDB collection (built by main.py's docling pipeline)
# ---------------------------------------------------------------------------
client = chromadb.PersistentClient(path=str(PROJECT_DIR / "rag_vector_db"))
emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)
collection = client.get_collection(
    name="docling_knowledge_base", embedding_function=emb_fn
)
print(f"✅ Loaded ChromaDB collection with {collection.count()} chunks")


# ---------------------------------------------------------------------------
# Postgres (optional). Writes happen only when your laptop is on AND pg is up.
# ---------------------------------------------------------------------------
class VisitorStore:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._conn = None
        self.enabled = False

    def connect(self):
        try:
            import psycopg2
            self._conn = psycopg2.connect(self.dsn)
            self._conn.autocommit = True
            self._init_schema()
            self.enabled = True
            print("✅ PostgreSQL connected — visitor logging ON")
        except Exception as e:
            self.enabled = False
            print(f"⚠️ PostgreSQL unavailable (visitor logs disabled): {e}")

    def _init_schema(self):
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS visitor_logs (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT now(),
                session_id TEXT,
                project TEXT,
                event TEXT,
                detail TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS waitlist (
                id BIGSERIAL PRIMARY KEY,
                ts TIMESTAMPTZ DEFAULT now(),
                name TEXT,
                email TEXT UNIQUE,
                note TEXT
            );
            """
        )
        cur.close()

    def log(self, session_id, project, event, detail=""):
        if not self.enabled:
            return
        try:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO visitor_logs(session_id, project, event, detail) "
                "VALUES (%s,%s,%s,%s)",
                (session_id, project, event, detail),
            )
            cur.close()
        except Exception as e:
            print(f"⚠️ visitor log failed: {e}")

    def signup(self, name, email, note=""):
        if not self.enabled:
            return False, "database unavailable"
        try:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO waitlist(name, email, note) VALUES (%s,%s,%s) "
                "ON CONFLICT (email) DO UPDATE SET name=EXCLUDED.name, note=EXCLUDED.note",
                (name, email, note),
            )
            cur.close()
            return True, "ok"
        except Exception as e:
            return False, str(e)

    def today_stats(self):
        """Return basic counts + recent rows + time-series for the dashboard."""
        if not self.enabled:
            return {"enabled": False, "visits": 0, "questions": 0,
                    "waitlist": 0, "recent": [], "waitlist_rows": [],
                    "events_by_hour": [], "waitlist_by_day": []}
        try:
            cur = self._conn.cursor()
            def one(sql, params=()):
                cur.execute(sql, params)
                return cur.fetchone()[0]
            visits = one("SELECT COUNT(*) FROM visitor_logs "
                         "WHERE ts >= CURRENT_DATE")
            questions = one("SELECT COUNT(*) FROM visitor_logs "
                            "WHERE ts >= CURRENT_DATE AND event='question'")
            waitlist = one("SELECT COUNT(*) FROM waitlist")
            cur.execute(
                "SELECT ts, project, event, detail FROM visitor_logs "
                "WHERE ts >= CURRENT_DATE ORDER BY ts DESC LIMIT 50")
            recent = cur.fetchall()
            cur.execute(
                "SELECT name, email, note, ts FROM waitlist "
                "ORDER BY ts DESC LIMIT 50")
            wl = cur.fetchall()
            # time-series: events per hour (last 12h) + cumulative waitlist by day
            cur.execute(
                "SELECT to_char(date_trunc('hour', ts), 'HH24:00') AS hr, "
                "COUNT(*) FROM visitor_logs "
                "WHERE ts >= now() - interval '12 hours' "
                "GROUP BY 1 ORDER BY 1")
            events_by_hour = [{"hour": r[0], "count": r[1]} for r in cur.fetchall()]
            cur.execute(
                "SELECT to_char(date_trunc('day', ts), 'MM-DD') AS d, "
                "COUNT(*) FROM waitlist GROUP BY 1 ORDER BY 1")
            waitlist_by_day = [{"day": r[0], "count": r[1]} for r in cur.fetchall()]
            cur.close()
            stats = {
                "enabled": True, "visits": visits, "questions": questions,
                "waitlist": waitlist,
                "recent": [
                    {"ts": str(r[0]), "project": r[1], "event": r[2],
                     "detail": (r[3] or "")[:160]}
                    for r in recent],
                "waitlist_rows": [
                    {"name": r[0], "email": r[1],
                     "note": (r[2] or "")[:120], "ts": str(r[3])}
                    for r in wl],
                "events_by_hour": events_by_hour,
                "waitlist_by_day": waitlist_by_day,
            }
            self._snapshot(stats)
            return stats
        except Exception as e:
            print(f"⚠️ today_stats failed: {e}")
            return {"enabled": False, "visits": 0, "questions": 0,
                    "waitlist": 0, "recent": [], "waitlist_rows": [],
                    "events_by_hour": [], "waitlist_by_day": []}

    def _snapshot(self, stats: dict):
        """Persist a timestamped JSON snapshot into dashboard_log/ (local copy)."""
        try:
            DASHBOARD_LOG_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            snap = {"generated_at": stamp, **stats}
            (DASHBOARD_LOG_DIR / f"snapshot_{stamp}.json").write_text(
                json.dumps(snap, indent=2, default=str), encoding="utf-8")
            # keep only the latest 20 snapshots
            snaps = sorted(DASHBOARD_LOG_DIR.glob("snapshot_*.json"))
            for old in snaps[:-20]:
                old.unlink()
        except Exception as e:
            print(f"⚠️ dashboard snapshot failed: {e}")


store = VisitorStore(CONFIG["postgres"]["dsn"])


# ---------------------------------------------------------------------------
# Answer cache — repeat/similar questions return instantly without hitting GPU.
# Keyed on the cleaned query so "what is X" and "can u say what is X" match.
# ---------------------------------------------------------------------------
from datetime import datetime

_ANSWER_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 3600.0  # 1 hour


def _cache_key(q: str) -> str:
    return _clean_query(q)


def _cache_get(q: str):
    k = _cache_key(q)
    if k in _ANSWER_CACHE:
        ans, ts = _ANSWER_CACHE[k]
        if (datetime.now().timestamp() - ts) < _CACHE_TTL:
            return ans
        del _ANSWER_CACHE[k]
    return None


def _cache_put(q: str, ans: str):
    _ANSWER_CACHE[_cache_key(q)] = (ans, datetime.now().timestamp())


# ---------------------------------------------------------------------------
# SERIAL request queue — one answer at a time (per spec: queue the rest)
# ---------------------------------------------------------------------------
_request_queue = deque()
_queue_lock = asyncio.Lock()
_current = None  # (session_id, start_time)


def _now_session() -> str:
    return str(uuid.uuid4())[:12]


# ---------------------------------------------------------------------------
# SSE chat (one-at-a-time)
# ---------------------------------------------------------------------------
def _clean_query(q: str) -> str:
    """Strip low-signal filler so retrieval matches on content words."""
    stop = {"can", "u", "you", "say", "tell", "me", "what", "is", "are",
            "do", "does", "the", "a", "an", "of", "to", "in", "on", "for",
            "about", "please", "hi", "hello", "explain", "page"}
    words = [w for w in q.lower().replace("?", " ").split() if w not in stop]
    return " ".join(words) if words else q


import re
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

# ---- Light rule-based router (Step 1): no LLM, just pattern match ----
_PAGE_RE = re.compile(r"page\s+(\d+)", re.IGNORECASE)
def route_query(q: str):
    m = _PAGE_RE.search(q)
    if m:
        return ("page", int(m.group(1)))
    return ("hybrid", None)


# ---- BM25 lexical index (Step 2): built once at startup from the collection ----
def _tokenize(t: str) -> list:
    return re.findall(r"\w+", t.lower())


_all = collection.get()
_BM25_DOCS = _all["documents"]
_BM25_IDS = _all["ids"]
_BM25 = BM25Okapi([_tokenize(d) for d in _BM25_DOCS])

# ---- Local CrossEncoder reranker (Step 3) ----
_RERANKER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


# ---- Hybrid retrieval + Reciprocal Rank Fusion (Step 2) ----
def sync_hybrid_search(query: str, n_results: int = 10):
    clean_q = _clean_query(query)
    sem = collection.query(query_texts=[clean_q], n_results=n_results)["ids"][0]
    lex_scores = _BM25.get_scores(_tokenize(clean_q))
    lex = [_BM25_IDS[i] for i in sorted(range(len(lex_scores)),
            key=lambda i: lex_scores[i], reverse=True)[:n_results]]
    rrf = {}
    for r, cid in enumerate(sem):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (r + 60)
    for r, cid in enumerate(lex):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (r + 60)
    top_ids = [c for c, _ in sorted(rrf.items(), key=lambda x: x[1], reverse=True)[:n_results]]
    res = collection.get(ids=top_ids)
    order = {c: i for i, c in enumerate(top_ids)}
    paired = sorted(zip(res["documents"], res["metadatas"]),
                    key=lambda x: order.get(x[1].get("id"), 0))
    return [d for d, _ in paired], [m for _, m in paired]


# Cosine distance above this = not relevant enough to ground an answer.
# (1.0 = orthogonal/unrelated, 0.0 = identical. Our KB top hits land 0.30-0.48;
#  off-topic queries sit well above 0.50, so they correctly get "not in KB".)
_RELEVANCE_CUTOFF = 0.50

# Cap retrieved context so the local 9B model stays within its 32K window.
_MAX_CONTEXT_CHARS = 26000


def build_system_prompt(retrieved_context: str, had_context: bool) -> str:
    if not had_context:
        # No relevant chunks passed the relevance threshold — be honest, don't guess.
        return (
            "You are a retrieval-augmented assistant. No relevant context was "
            "found in the knowledge base for this question. Reply exactly with: "
            "\"I don't have information about that in my knowledge base.\" "
            "Do NOT use outside knowledge and do NOT add anything else."
        )
    return f"""You are an expert AI Engineering Assistant teaching a learner.
Answer the user's question using ONLY the CONTEXT below. Write the final answer directly — no meta-commentary, no "Looking at the CONTEXT", no narration.
Give a SUBSTANTIVE explanation (at least 3-4 sentences) that uses the specific details, examples, and analogies present in the CONTEXT. Do NOT stop at a one-line definition when the CONTEXT contains more.
If the fact is absent from the CONTEXT, say so briefly. Do not use outside knowledge. Never mention chunk numbers, source labels, or section markers.

EXAMPLE
Question: what is rag?
Good answer: RAG (Retrieval-Augmented Generation) lets an LLM look up relevant information from your own data before generating an answer. Think of it like an open-book vs closed-book exam: without RAG the model only uses what it was trained on (risking hallucination and stale knowledge), while with RAG it retrieves the right passages first and answers from them. The typical pipeline is: load documents, split them into chunks, embed the chunks into vectors, store them in a vector database, then at query time retrieve the most similar chunks and feed them to the LLM as context.

CONTEXT:
{retrieved_context}
"""


async def generate_rag_stream(user_question: str, session_id: str):
    loop = asyncio.get_running_loop()
    with tracer.start_as_current_span("rag_answer") as span:
        span.set_attribute("session.id", session_id)
        span.set_attribute("question", user_question[:120])

        # 0) answer cache — repeat/similar questions return instantly
        cached = _cache_get(user_question)
        if cached is not None:
            span.set_attribute("cache.hit", True)
            yield f"data: {json.dumps({'token': cached})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            return

        try:
            # 1) route: "page N" -> page fast-path; otherwise hybrid
            route, page_n = route_query(user_question)
            clean_q = _clean_query(user_question)

            if route == "page":
                # Step 4 — page-index fast path: skip vector/BM25 entirely
                res = collection.get(where={"page": page_n})
                docs, metas = res["documents"], res["metadatas"]
                # still apply relevance ordering by embedding similarity of the query
                if docs:
                    sim = collection.query(query_texts=[clean_q], n_results=len(docs),
                                           where={"page": page_n})
                    order = {c: i for i, c in enumerate(sim["ids"][0])}
                    paired = sorted(zip(docs, metas),
                                    key=lambda x: order.get(x[1].get("id"), 0))
                    docs, metas = [d for d, _ in paired], [m for _, m in paired]
            else:
                # Step 2+3 — hybrid (dense + BM25) -> RRF -> CrossEncoder rerank
                docs, metas = await loop.run_in_executor(None, sync_hybrid_search, clean_q)
                # Relevance guard: drop chunks whose semantic distance is too high
                # (grounding — keeps off-topic queries honest). RRF ranks them, but
                # if the top match is genuinely unrelated, we should not answer.
                dist_res = collection.query(query_texts=[clean_q], n_results=len(docs))
                dist_map = {}
                for cid, dist in zip(dist_res["ids"][0], dist_res["distances"][0]):
                    dist_map[cid] = dist
                kept = [(d, m) for d, m in zip(docs, metas)
                        if dist_map.get(m.get("id"), 1.0) <= _RELEVANCE_CUTOFF]
                if kept:
                    docs, metas = zip(*kept)
                    docs, metas = list(docs), list(metas)
                if docs:
                    pairs = [(clean_q, d) for d in docs]
                    scores = _RERANKER.predict(pairs)
                    # sort by score ONLY — comparing the dict metadata directly
                    # ('<' not supported between dicts) fails whenever scores tie.
                    ranked = sorted(zip(scores, docs, metas),
                                    key=lambda x: x[0], reverse=True)
                    docs = [d for _, d, _ in ranked]
                    metas = [m for _, _, m in ranked]
                    docs = docs[:6]
                    metas = metas[:6]

            # RBAC (Step 6): only surface public chunks (premium would be filtered here)
            allowed = {"public"}
            filtered = [(d, m) for d, m in zip(docs, metas)
                        if m.get("access", "public") in allowed]

            retrieved_context = ""
            sources = []
            for doc, m in filtered:
                if not doc or not doc.strip():
                    continue
                # Strip any "--- Chunk N ---" marker so the model never echoes it.
                clean_doc = "\n".join(
                    ln for ln in doc.splitlines() if not ln.strip().startswith("--- Chunk")
                ).strip()
                if not clean_doc:
                    continue
                # fit_context (Step 6): cap context to keep the local 9B model in-window
                if len(retrieved_context) + len(clean_doc) > _MAX_CONTEXT_CHARS:
                    break
                retrieved_context += clean_doc + "\n\n"
                sources.append(f"{m['source']} :: {m['headings']}")

            had_context = bool(retrieved_context.strip())
            system_prompt = build_system_prompt(retrieved_context, had_context)
            span.set_attribute("context.chunks", len(sources))
            span.set_attribute("route", route)

            # 2) generate via OpenRouter (cloud LLM — no local GPU needed, so the
            #    site works even when the laptop is on but Ollama isn't, and is
            #    portable to cloud hosting). Default model openrouter/free.
            from openai import OpenAI
            api_key = (CONFIG.get("openrouter_api_key")
                       or os.environ.get("OPENROUTER_API_KEY")
                       or _hermes_openrouter_key())
            if not api_key:
                yield f"data: {json.dumps({'error': 'OpenRouter API key not configured. Set OPENROUTER_API_KEY or openrouter_api_key in server_config.json.'})}\n\n"
                return
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
                default_headers={"HTTP-Referer": "https://localhost/rag",
                                 "X-Title": "AetherMind"},
            )
            om_model = CONFIG.get("openrouter_model", "openrouter/free")
            response_stream = client.chat.completions.create(
                model=om_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_question},
                ],
                stream=True,
            )
            tok_count = 0
            full_answer = []
            for chunk in response_stream:
                token = ""
                try:
                    if chunk.choices and chunk.choices[0].delta:
                        token = chunk.choices[0].delta.content or ""
                except Exception:
                    token = ""
                if token:
                    full_answer.append(token)
                    tok_count += 1
                    yield f"data: {json.dumps({'token': token})}\n\n"
                await asyncio.sleep(0)
            span.set_attribute("tokens.emitted", tok_count)

            # cache the complete answer for future identical/similar questions
            _cache_put(user_question, "".join(full_answer))

            # done — log the question + sources
            store.log(session_id, "project_rag", "answer",
                      json.dumps({"q": user_question, "sources": sources[:3]}))
            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            span.record_exception(e)
            store.log(session_id, "project_rag", "error", str(e))
            yield f"data: {json.dumps({'error': str(e)})}\n\n"


async def queue_worker():
    """Processes one queued chat request at a time, strictly serial."""
    global _current
    while True:
        async with _queue_lock:
            if not _request_queue:
                await asyncio.sleep(0.2)
                continue
            item = _request_queue.popleft()
        _current = (item["session_id"], time.time())
        try:
            async for piece in generate_rag_stream(item["question"], item["session_id"]):
                await item["enqueue"](piece)
        finally:
            _current = None
            await item["enqueue"](None)  # signal end


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    asyncio.create_task(queue_worker())
    store.connect()
    ngrok_ref = _open_tunnel()  # returns (ngrok, public_url) or (None, None)
    try:
        yield
    finally:
        if ngrok_ref and ngrok_ref[0]:
            try:
                ngrok_ref[0].disconnect(ngrok_ref[1])
            except Exception:
                pass


app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    pos = len(_request_queue)
    status = "busy" if _current else "idle"
    return {
        "status": "ok",
        "chunks": collection.count(),
        "queue_position": pos,
        "current_request": bool(_current),
        "gpu_model": CONFIG["ollama_model"],
        "postgres": store.enabled,
    }


# ---------------------------------------------------------------------------
# Upload endpoint — adds a user's PDF into the LIVE collection (same pipeline),
# storing split chunks under rag_pdfs/temp_split_chunks, then rebuilds BM25 so
# hybrid search sees the new chunks immediately.
# ---------------------------------------------------------------------------
from fastapi import UploadFile, File
import shutil

_UPLOAD_LOCK = asyncio.Lock()


def _rebuild_bm25():
    """Rebuild the in-memory BM25 lexical index from the current collection."""
    global _BM25_DOCS, _BM25_IDS, _BM25
    _all = collection.get()
    _BM25_DOCS = _all["documents"]
    _BM25_IDS = _all["ids"]
    _BM25 = BM25Okapi([_tokenize(d) for d in _BM25_DOCS])


@app.post("/api/upload")
async def upload_endpoint(file: UploadFile = File(...)):
    name = (file.filename or "").strip().lower()
    if not name.endswith((".pdf", ".docx", ".txt", ".odt", ".pptx")):
        return JSONResponse({"ok": False, "error": "Unsupported file type"}, status_code=400)

    # 1) save upload to the project's temp_split_chunks folder
    temp_dir = PROJECT_DIR / "rag_pdfs" / "temp_split_chunks"
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^a-z0-9._-]", "_", Path(file.filename).stem)[:60]
    dest = temp_dir / f"{safe_stem}_{uuid.uuid4().hex[:8]}{Path(file.filename).suffix.lower()}"
    try:
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"save failed: {e}"}, status_code=500)

    # 2) chunk with the SAME docling pipeline (reuses main.py)
    try:
        chunks = await asyncio.to_thread(
            rag.chunk_single_pdf, str(dest), str(temp_dir)
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"ingest failed: {e}"}, status_code=500)

    if not chunks:
        return JSONResponse({"ok": False, "error": "No content extracted from file"}, status_code=422)

    # 3) upsert into the LIVE collection (append — never wipe existing KB)
    docs, metas, ids = [], [], []
    for i, c in enumerate(chunks):
        docs.append(c["text"])
        headings = " > ".join(c["headings"]) if c["headings"] else "No Header"
        metas.append({
            "source": c["source"],
            "headings": headings,
            "page": int(c.get("page", -1)),
            "access": "public",
        })
        ids.append(f"upload_{uuid.uuid4().hex[:12]}_{i}")
    try:
        collection.upsert(documents=docs, metadatas=metas, ids=ids)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"vector store failed: {e}"}, status_code=500)

    # 4) rebuild BM25 so hybrid retrieval includes the new chunks
    _rebuild_bm25()

    return {
        "ok": True,
        "filename": file.filename,
        "chunks_added": len(chunks),
        "total_chunks": collection.count(),
        "note": "File added to the knowledge base. Ask a question about it now.",
    }


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    body = await request.json()
    question = (body.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "Question cannot be empty"}, status_code=400)

    session_id = _now_session()
    store.log(session_id, "project_rag", "question", question)

    queue_pos = len(_request_queue) + (1 if _current else 0)

    # Channel the stream back to the HTTP response
    async def event_stream():
        q = asyncio.Queue()
        item = {"question": question, "session_id": session_id, "enqueue": q.put}
        _request_queue.append(item)
        # first frame: tell client its queue position
        yield f"data: {json.dumps({'queued': True, 'position': queue_pos})}\n\n"
        while True:
            piece = await q.get()
            if piece is None:
                break
            yield piece

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/waitlist")
async def waitlist_endpoint(request: Request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    note = (body.get("note") or "").strip()
    if not email or "@" not in email:
        return JSONResponse({"ok": False, "error": "valid email required"}, status_code=400)
    ok, msg = store.signup(name, email, note)
    store.log(_now_session(), "project_rag_hybrid", "waitlist_signup", email)
    return {"ok": ok, "message": msg}


@app.get("/api/config")
async def public_config():
    return {
        "project": "project_rag",
        "model": "local Ollama (RTX 5070)",
        "allow_download": CONFIG["allow_download"],
    }


@app.get("/dashboard")
async def dashboard(request: Request):
    """Local-only owner dashboard: today's visitors, questions, waitlist."""
    client = request.client.host if request.client else ""
    if client not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": "owner-only"}, status_code=403)
    stats = store.today_stats()
    html = _render_dashboard(stats)
    return HTMLResponse(html)


@app.get("/api/dashboard-data")
async def dashboard_data(request: Request):
    """Live JSON feed for the interactive dashboard (localhost only)."""
    client = request.client.host if request.client else ""
    if client not in ("127.0.0.1", "::1", "localhost"):
        return JSONResponse({"error": "owner-only"}, status_code=403)
    return store.today_stats()


def _render_dashboard(s: dict) -> str:
    enabled = s.get("enabled")
    status = "✅ Postgres ON" if enabled else "⚠️ Postgres OFF"
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>AetherMind · Owner Dashboard</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head><body class="bg-zinc-950 text-zinc-100 min-h-screen p-6 font-sans">
<div class="max-w-6xl mx-auto">
  <div class="flex items-center justify-between mb-1">
    <h1 class="text-2xl font-bold">AetherMind — Owner Dashboard</h1>
    <span id="live" class="text-xs text-emerald-400">● live</span>
  </div>
  <p class="text-xs text-zinc-400 mb-6">{status} · auto-refreshes every 5s · data stored in <code>dashboard_log/</code></p>
  <div class="grid grid-cols-3 gap-4 mb-8">
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4"><div id="k-visits" class="text-3xl font-bold">{s.get('visits',0)}</div><div class="text-xs text-zinc-400">Events today</div></div>
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4"><div id="k-questions" class="text-3xl font-bold">{s.get('questions',0)}</div><div class="text-xs text-zinc-400">Questions asked</div></div>
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4"><div id="k-waitlist" class="text-3xl font-bold">{s.get('waitlist',0)}</div><div class="text-xs text-zinc-400">Waitlist total</div></div>
  </div>
  <div class="grid grid-cols-2 gap-6 mb-8">
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4"><h2 class="text-sm font-semibold mb-3">Activity (last 12h)</h2><canvas id="evChart" height="120"></canvas></div>
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4"><h2 class="text-sm font-semibold mb-3">Waitlist signups by day</h2><canvas id="wlChart" height="120"></canvas></div>
  </div>
  <h2 class="text-lg font-semibold mb-2">Today's Activity</h2>
  <div class="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden mb-8">
    <table class="w-full"><thead class="bg-zinc-800/50 text-zinc-400 text-xs">
      <tr><th class="px-2 py-1 text-left">Time</th><th class="px-2 py-1 text-left">Project</th>
      <th class="px-2 py-1 text-left">Event</th><th class="px-2 py-1 text-left">Detail</th></tr>
    </thead><tbody id="recent-body"></tbody></table>
  </div>
  <h2 class="text-lg font-semibold mb-2">Waitlist Signups</h2>
  <div class="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
    <table class="w-full"><thead class="bg-zinc-800/50 text-zinc-400 text-xs">
      <tr><th class="px-2 py-1 text-left">Name</th><th class="px-2 py-1 text-left">Email</th>
      <th class="px-2 py-1 text-left">Note</th><th class="px-2 py-1 text-left">Joined</th></tr>
    </thead><tbody id="wl-body"></tbody></table>
  </div>
</div>
<script>
function esc(x){{ return (x||'').toString().replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}})[c]); }}
let evChart, wlChart;
async function load() {{
  try {{
    const r = await fetch('/api/dashboard-data');
    const s = await r.json();
    document.getElementById('k-visits').textContent = s.visits ?? 0;
    document.getElementById('k-questions').textContent = s.questions ?? 0;
    document.getElementById('k-waitlist').textContent = s.waitlist ?? 0;
    document.getElementById('recent-body').innerHTML = (s.recent||[]).map(r =>
      `<tr><td class='px-2 py-1 text-xs'>${{r.ts.slice(0,19)}}</td><td class='px-2 py-1 text-xs'>${{esc(r.project)}}</td><td class='px-2 py-1 text-xs'>${{esc(r.event)}}</td><td class='px-2 py-1 text-xs text-zinc-400'>${{esc(r.detail)}}</td></tr>`).join('') || "<tr><td colspan='4' class='px-2 py-2 text-xs text-zinc-500'>no activity today</td></tr>";
    document.getElementById('wl-body').innerHTML = (s.waitlist_rows||[]).map(w =>
      `<tr><td class='px-2 py-1 text-xs'>${{esc(w.name||'—')}}</td><td class='px-2 py-1 text-xs'>${{esc(w.email)}}</td><td class='px-2 py-1 text-xs text-zinc-400'>${{esc(w.note)}}</td><td class='px-2 py-1 text-xs'>${{w.ts.slice(0,19)}}</td></tr>`).join('') || "<tr><td colspan='4' class='px-2 py-2 text-xs text-zinc-500'>no signups</td></tr>";
    drawCharts(s);
    document.getElementById('live').textContent = '● live ' + new Date().toLocaleTimeString();
  }} catch(e) {{ document.getElementById('live').textContent = '● error'; }}
}}
function drawCharts(s) {{
  const ev = s.events_by_hour || [];
  const evData = {{ labels: ev.map(d=>d.hour), datasets:[{{ label:'events', data: ev.map(d=>d.count), borderColor:'#34d399', backgroundColor:'rgba(52,211,153,.2)', fill:true, tension:.3 }}] }};
  if (evChart) {{ evChart.data = evData; evChart.update(); }} else evChart = new Chart(document.getElementById('evChart'), {{type:'line', data:evData, options:{{plugins:{{legend:{{display:false}}}}, scales:{{x:{{ticks:{{color:'#71717a'}}}}, y:{{ticks:{{color:'#71717a'}}, beginAtZero:true}}}}}}}});
  const wl = s.waitlist_by_day || [];
  const wlData = {{ labels: wl.map(d=>d.day), datasets:[{{ label:'signups', data: wl.map(d=>d.count), backgroundColor:'#a78bfa' }}] }};
  if (wlChart) {{ wlChart.data = wlData; wlChart.update(); }} else wlChart = new Chart(document.getElementById('wlChart'), {{type:'bar', data:wlData, options:{{plugins:{{legend:{{display:false}}}}, scales:{{x:{{ticks:{{color:'#71717a'}}}}, y:{{ticks:{{color:'#71717a'}}, beginAtZero:true}}}}}}}});
}}
load(); setInterval(load, 5000);
</script></body></html>"""


# ---------------------------------------------------------------------------
# Static UI + download
# ---------------------------------------------------------------------------
@app.get("/")
async def index():
    idx = UI_DIR / "index.html"
    if idx.exists():
        resp = FileResponse(idx)
        # prevent browsers from caching the SPA shell (UI updates must show immediately)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    return HTMLResponse("<h1>AetherMind local RAG is running.</h1>")


# --- "What this model knows" page + downloadable README guide ---
_KNOWLEDGE_GUIDE_MD = """# AetherMind — What This Model Knows

AetherMind is a local RAG assistant. It answers ONLY from a curated knowledge
base of PDFs about Retrieval-Augmented Generation (RAG) and AI agents. It does
not browse the internet, so questions outside this scope will be answered with
"that is not in my knowledge base."

## Knowledge areas
1. RAG fundamentals — when to use RAG vs fine-tuning, failure modes.
2. Vector databases & retrieval — embeddings, chunking, vectorless / page-index retrieval, TurboVec.
3. Agentic RAG, agent memory & MCP — retrieval decisions, cross-turn memory, tool/DB access via MCP.
4. Production RAG — architecture blueprints, cost/latency, evaluation, security guardrails.

## Example questions (use-case style, not generic)
- When should I use RAG instead of fine-tuning, and what are the trade-offs?
- Walk through a real production example: how would KARLA-style retrieval be wired into a support bot, and where does it get used?
- What chunk size and overlap give the best retrieval for long technical PDFs, and why?
- Compare vectorless RAG with page-index retrieval against classic vector search — when is each right?
- Design a memory architecture for an agent that recalls facts across a 50-turn conversation without blowing up the context window.
- What is MCP and how do I let my RAG agent call an external tool or database safely?
- Give me an architecture blueprint for a production RAG service handling 10k questions/day on a single GPU.
- What security risks show up when agents can read private docs, and which guardrails matter?
- How do I evaluate whether my RAG system is good enough before launching?
"""


@app.get("/knowledge")
async def knowledge_page():
    p = UI_DIR / "knowledge.html"
    if p.exists():
        resp = FileResponse(p)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp
    return HTMLResponse("<h1>Knowledge page not found.</h1>", status_code=404)


@app.get("/api/knowledge-guide")
async def knowledge_guide():
    return StreamingResponse(
        iter([_KNOWLEDGE_GUIDE_MD]),
        media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=\"AetherMind-Knowledge-Guide.md\""},
    )


@app.get("/aether-docs")
async def aether_docs():
    return FileResponse(UI_DIR / "aether-docs.html")


@app.get("/download/aether")
async def download_aether():
    # Redirect to the GitHub Release (free, fast CDN) so the 135 MB installer
    # never burns this server's tunnel bandwidth. Installs to
    # %LOCALAPPDATA%\Aether with desktop + start-menu shortcuts; no admin/UAC.
    store.log(_now_session(), "Aether-Setup", "download-redirect")
    return RedirectResponse(
        "https://github.com/RekapalliVasudeva-MBU/aether-desktop/releases/download/v1.2.0/Aether-Setup.exe",
        status_code=302,
    )


@app.get("/download/desktop")
async def download_desktop():
    if not CONFIG["allow_download"]:
        return JSONResponse({"error": "downloads disabled"}, status_code=403)
    # Windows installer (Inno Setup) — real .exe installer
    exe_path = PROJECT_DIR / "dist" / "ProjectRAG-Setup.exe"
    if not exe_path.exists():
        return JSONResponse(
            {"error": "build the installer first: iscc installer.iss"},
            status_code=404,
        )
    store.log(_now_session(), "ProjectRAG-Setup", "download")
    return FileResponse(
        exe_path,
        filename="ProjectRAG-Setup.exe",
        media_type="application/octet-stream",
    )


if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


# ---------------------------------------------------------------------------
# Lifespan: ngrok tunnel
# ---------------------------------------------------------------------------
def _open_tunnel():
    # Public URL is provided by an external tunnel (cloudflared quick tunnel),
    # launched separately so the 135 MB installer never burns a metered
    # tunnel's bandwidth. The server only binds locally on CONFIG["port"].
    print(f"\n{'=' * 60}")
    print("AETHERMIND LOCAL RAG SERVER ONLINE (local only)")
    print(f"Local URL:  http://{CONFIG['host']}:{CONFIG['port']}/")
    print("Public URL is served via cloudflared (see Agent_OS.cmd).")
    print("=" * 60 + "\n")
    return None, None


if __name__ == "__main__":
    import uvicorn

    print(f"\n[init] RAG chunks available: {collection.count()}")
    print(f"[init] Generator: local Ollama ({CONFIG['ollama_model']}) on your GPU")
    print(f"[init] Requests run ONE AT A TIME (serial queue).\n")

    config = uvicorn.Config(
        app,
        host=CONFIG["host"],
        port=CONFIG["port"],
        log_level="info",
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
