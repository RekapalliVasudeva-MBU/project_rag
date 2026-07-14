"""
AETHERMIND RAG — Evaluation layer (Step 5 of the Master Approach)
=================================================================

Offline evaluation that proves the hybrid pipeline (dense + BM25 -> RRF ->
CrossEncoder rerank) beats the old pure-vector retrieval.

Metrics
-------
  recall@K           : did the golden source PDF appear in the top-K retrieved docs?
  context_recall     : does the generated answer use the retrieved context?
                       (judged locally by Ollama — no external calls)
  faithfulness       : is the answer grounded in the context (no hallucination)?
                       (judged locally by Ollama)

Run BEFORE/AFTER the retrieval change to show the gain:

    python eval_rag.py            # evaluates both OLD and NEW on the same set

The script imports the live collection + helpers from server.py so it always
measures what the running site actually uses.
"""
import json
import sys
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

# --- reuse the real collection + retrieval helpers from the server ---
import server as rag
from rank_bm25 import BM25Okapi

collection = rag.collection
_clean_query = rag._clean_query

# ---------------------------------------------------------------------------
# Golden eval set: (question, expected_source_pdf)
# These are real topics covered by the knowledge base PDFs.
# ---------------------------------------------------------------------------
EVAL_QUESTIONS = [
    ("what is RAG and why does it matter", "01_RAG_Fundamentals.pdf"),
    ("explain the complete RAG architecture pipeline", "01_RAG_Fundamentals.pdf"),
    ("what is a vector database and how does HNSW work", "02_Vector_Databases_Deep_Dive.pdf"),
    ("how does hybrid retrieval combine dense and sparse search", "03_Vectorless_RAG_and_PageIndex.pdf"),
    ("what is page index and how does it speed up retrieval", "03_Vectorless_RAG_and_PageIndex.pdf"),
    ("what are the differences between naive advanced and agentic RAG", "01_RAG_Fundamentals.pdf"),
    ("how does reranking improve retrieval quality", "03_Vectorless_RAG_and_PageIndex.pdf"),
    ("what is the BM25 algorithm", "03_Vectorless_RAG_and_PageIndex.pdf"),
    ("what is context recall in RAG evaluation", "05_RAG_Evaluation_RAGAS_DeepEval.pdf"),
    ("how do you evaluate faithfulness of a RAG answer", "05_RAG_Evaluation_RAGAS_DeepEval.pdf"),
]


# --- OLD retrieval: pure dense vector (what the site used before) ---
def old_retrieve(query, n=5):
    res = collection.query(query_texts=[_clean_query(query)], n_results=n)
    return res["documents"][0], res["metadatas"][0]


# --- NEW retrieval: hybrid + RRF + CrossEncoder rerank (current site) ---
def new_retrieve(query, n=10, top=6):
    docs, metas = rag.sync_hybrid_search(query, n_results=n)
    # relevance guard (mirrors server.py)
    dist_res = collection.query(query_texts=[_clean_query(query)], n_results=len(docs))
    dist_map = {c: d for c, d in zip(dist_res["ids"][0], dist_res["distances"][0])}
    kept = [(d, m) for d, m in zip(docs, metas)
            if dist_map.get(m.get("id"), 1.0) <= rag._RELEVANCE_CUTOFF]
    if kept:
        docs, metas = zip(*kept)
        docs, metas = list(docs), list(metas)
    if not docs:
        return [], []
    pairs = [(_clean_query(query), d) for d in docs]
    scores = rag._RERANKER.predict(pairs)
    ranked = sorted(zip(scores, docs, metas), reverse=True)
    docs = [d for _, d, _ in ranked][:top]
    metas = [m for _, _, m in ranked][:top]
    return docs, metas


def recall_at_k(metas, golden_source, k=5):
    """1 if golden source appears in top-k metadata, else 0."""
    for m in metas[:k]:
        if m.get("source") == golden_source:
            return 1
    return 0


def judge(question, context, answer):
    """Local Ollama judges context_recall + faithfulness. Returns (recall, faith)."""
    prompt = (
        "You are an evaluation judge. Given the QUESTION, the retrieved CONTEXT, "
        "and the ANSWER, reply with exactly two lines:\n"
        "context_recall: yes/no  (does the context contain the info needed to answer?)\n"
        "faithfulness: yes/no    (is the answer fully supported by the context, no hallucination?)\n\n"
        f"QUESTION: {question}\n\nCONTEXT:\n{context[:4000]}\n\nANSWER:\n{answer[:1500]}\n"
    )
    try:
        import ollama
        out = ollama.chat(model=rag.CONFIG["ollama_model"],
                          messages=[{"role": "user", "content": prompt}],
                          options={"keep_alive": "0"})
        text = out["message"]["content"].lower()
    except Exception as e:
        return ("n/a", f"judge error: {e}")
    cr = "yes" in text.split("context_recall")[1].split("\n")[0] if "context_recall" in text else False
    fa = "yes" in text.split("faithfulness")[1].split("\n")[0] if "faithfulness" in text else False
    return (cr, fa)


def generate_answer(context, question):
    prompt = rag.build_system_prompt(context, bool(context.strip()))
    try:
        import ollama
        out = ollama.chat(model=rag.CONFIG["ollama_model"],
                          messages=[{"role": "system", "content": prompt},
                                    {"role": "user", "content": question}],
                          options={"keep_alive": "0"})
        return out["message"]["content"].strip()
    except Exception as e:
        return f"[gen error: {e}]"


def evaluate(retriever, label):
    print(f"\n{'='*70}\n  {label}\n{'='*70}")
    total = len(EVAL_QUESTIONS)
    r5 = r6 = cr_ok = fa_ok = 0
    for q, gold in EVAL_QUESTIONS:
        docs, metas = retriever(q)
        r5 += recall_at_k(metas, gold, 5)
        r6 += recall_at_k(metas, gold, 6)
        ctx = "\n\n".join(docs)
        ans = generate_answer(ctx, q)
        cr, fa = judge(q, ctx, ans)
        if cr == True:
            cr_ok += 1
        if fa == True:
            fa_ok += 1
        print(f"  • {q[:48]:48s} | R@5={recall_at_k(metas,gold,5)} R@6={recall_at_k(metas,gold,6)} "
              f"| cRec={cr} faith={fa} | gold={gold[:18]}")
    print(f"\n  recall@5 = {r5}/{total} ({100*r5/total:.0f}%)")
    print(f"  recall@6 = {r6}/{total} ({100*r6/total:.0f}%)")
    print(f"  context_recall = {cr_ok}/{total} ({100*cr_ok/total:.0f}%)")
    print(f"  faithfulness   = {fa_ok}/{total} ({100*fa_ok/total:.0f}%)")
    return {"recall@5": r5/total, "recall@6": r6/total,
            "context_recall": cr_ok/total, "faithfulness": fa_ok/total}


if __name__ == "__main__":
    print(f"Loaded collection with {collection.count()} chunks")
    old_metrics = evaluate(old_retrieve, "OLD  — pure dense vector (n=5)")
    new_metrics = evaluate(new_retrieve, "NEW  — hybrid + RRF + CrossEncoder rerank (top-6)")
    print("\n\n########## SUMMARY ##########")
    print(f"{'metric':16s} {'OLD':>8s} {'NEW':>8s} {'Δ':>8s}")
    for k in old_metrics:
        d = new_metrics[k] - old_metrics[k]
        print(f"{k:16s} {old_metrics[k]:8.2f} {new_metrics[k]:8.2f} {d:+8.2f}")
    Path("eval_results.json").write_text(json.dumps(
        {"old": old_metrics, "new": new_metrics}, indent=2))
    print("\nSaved eval_results.json")
