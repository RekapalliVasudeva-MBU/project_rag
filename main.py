"""
RAG System - Main Application (docling pipeline)
=================================================

Converted from First_Rag.ipynb. Uses the exact pipeline you built:
  - PyMuPDF          -> split large PDFs (with smart on-disk caching)
  - docling DocumentConverter  -> PDF -> markdown (layout + OCR)
  - docling HybridChunker      -> structural chunking (preserves H1/H2 headings)
  - ChromaDB         -> vector storage (headings kept in metadata)
  - Ollama (local)   -> answer generation
"""

import os
# Suppress the HuggingFace Windows symlink warning to keep terminal output clean
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# --- UTF-8 stdout/stderr shim (Windows) ---
# When launched from the Startup folder / a .cmd file, Python may inherit a
# non-UTF8 console codepage (e.g. cp1252). Printing emoji (🔧, 🚀) then throws
# UnicodeEncodeError and kills the process BEFORE it listens on the port.
# Forcing UTF-8 here makes the server survive a reboot. (Same fix already
# applied to the desktop app's main.py.)
import sys
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

import fitz  # PyMuPDF
from pathlib import Path
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    AcceleratorOptions,
    AcceleratorDevice,
)
from docling.chunking import HybridChunker
from transformers import AutoTokenizer
import chromadb
from chromadb.utils import embedding_functions
import ollama
import torch

# --- Hardware acceleration for docling ---
_device = AcceleratorDevice.CUDA if torch.cuda.is_available() else AcceleratorDevice.CPU
print(f"[init] Docling accelerator device: {_device}")


def build_converter():
    """Build the docling DocumentConverter exactly like the notebook."""
    pipeline_options = PdfPipelineOptions()
    # WARNING: Only set do_ocr=False if your PDFs are text-native.
    # If they are scanned images, keep True or you get blank text!
    pipeline_options.do_ocr = True
    pipeline_options.generate_page_images = False
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=4,
        device=_device,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    return converter


def get_pdf_chunks(pdf_path: Path, temp_folder: Path, max_pages: int = 8) -> list:
    """Splits large PDFs to protect VRAM. Caches chunks to disk for fault tolerance."""
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    if total_pages <= max_pages:
        doc.close()
        return [pdf_path]

    print(f"-> [{pdf_path.name}] has {total_pages} pages. Checking chunks...")
    chunks = []

    for start in range(0, total_pages, max_pages):
        end = min(start + max_pages - 1, total_pages - 1)
        chunk_path = temp_folder / f"{pdf_path.stem}_part_{start+1}_to_{end+1}.pdf"

        # SMART CACHING: Only split and save if the chunk doesn't already exist
        if not chunk_path.exists():
            chunk_doc = fitz.open()
            chunk_doc.insert_pdf(doc, from_page=start, to_page=end)
            chunk_doc.save(chunk_path)
            chunk_doc.close()

        chunks.append(chunk_path)

    doc.close()
    return chunks


SUPPORTED = [".pdf", ".docx", ".txt", ".odt", ".pptx"]


def process_rag_pipeline(source_folder: str, converter, chunker):
    """Full docling ingestion pipeline -> ChromaDB collection."""
    source_folder = Path(source_folder)
    temp_folder = source_folder / "temp_split_chunks"
    temp_folder.mkdir(exist_ok=True)

    final_database_chunks = []

    for pdf in source_folder.iterdir():
        # Only process main files, not the chunks inside the temp folder
        if not pdf.is_file() or pdf.suffix.lower() not in SUPPORTED:
            continue

        try:
            print(f"\n🔄 parsing...{pdf.name}...")
            work_units = (
                get_pdf_chunks(pdf, temp_folder, max_pages=8)
                if pdf.suffix.lower() == ".pdf"
                else [pdf]
            )

            for unit in work_units:
                if len(work_units) > 1:
                    print(f"  Processing chunk: {unit.name}...")
                doc = converter.convert(unit).document

                # Slice it intelligently using the Hybrid Chunker
                chunk_iter = chunker.chunk(dl_doc=doc)

                for chunk in chunk_iter:
                    # --- page number (docling >=0.5 stores it in doc_items[].prov) ---
                    page_no = -1
                    try:
                        prov = chunk.meta.doc_items[0].prov
                        if prov:
                            page_no = prov[0].page_no
                    except Exception:
                        page_no = -1
                    final_database_chunks.append(
                        {
                            "text": chunk.text,
                            "source": pdf.name,
                            "headings": chunk.meta.headings,  # preserves H1/H2 tags!
                            "page": page_no,
                        }
                    )

            print(f"✅ Successfully chunked {pdf.name}")

        except Exception as e:
            print(f"❌ Error processing {pdf.name}: {e}")
            import traceback

            traceback.print_exc()

    if not final_database_chunks:
        print("⚠️ No chunks generated")
        return [], None

    print(f"\n🎉 SUCCESS! Pipeline generated {len(final_database_chunks)} RAG chunks.")

    # --- Vector DB storage ---
    print("\n🔧 Initializing ChromaDB...")
    db_path = "./rag_vector_db"
    client = chromadb.PersistentClient(path=db_path)

    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    collection_name = "docling_knowledge_base"
    # Reset collection so stale entries from prior (non-docling) runs don't linger
    try:
        client.delete_collection(collection_name)
        print("🗑️ Cleared previous collection")
    except Exception:
        pass
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine"},
    )

    print(f"💾 Storing {len(final_database_chunks)} chunks in ChromaDB...")
    documents = []
    metadatas = []
    ids = []

    for i, chunk in enumerate(final_database_chunks):
        documents.append(chunk["text"])

        # ChromaDB wants flat metadata. Convert headings list -> readable string.
        headings_str = (
            " > ".join(chunk["headings"]) if chunk["headings"] else "No Header"
        )
        metadatas.append({
            "source": chunk["source"],
            "headings": headings_str,
            "page": int(chunk.get("page", -1)),
            "access": "public",
        })
        ids.append(f"chunk_{i}")

    batch_size = 100
    for i in range(0, len(documents), batch_size):
        end = min(i + batch_size, len(documents))
        collection.upsert(
            documents=documents[i:end],
            metadatas=metadatas[i:end],
            ids=ids[i:end],
        )
        print(f"   Saved batch {i} to {end - 1}...")

    print(f"\n✅ SUCCESS: All {len(final_database_chunks)} chunks embedded and permanently stored!")

    # Verification test query
    print("\n🧪 Testing knowledge base with sample query...")
    test_query = "What is the architecture of RAG?"
    results = collection.query(query_texts=[test_query], n_results=2)

    print("\n--- SAMPLE RESULTS ---")
    for i in range(len(results["documents"][0])):
        print(f"\nResult {i + 1}:")
        print(f"Source: {results['metadatas'][0][i]['source']}")
        print(f"Section: {results['metadatas'][0][i]['headings']}")
        print(f"Text: {results['documents'][0][i][:200]}...")

    return final_database_chunks, collection


# ---------------------------------------------------------------------------
# Incremental ingest for user-uploaded files (used by server.py /api/upload).
# Reuses the SAME docling converter + HybridChunker as the full pipeline.
# Returns chunk dicts (mirrors process_rag_pipeline's per-file extraction) but
# does NOT touch the collection — the caller upserts into the LIVE one.
# ---------------------------------------------------------------------------
_INGEST_CONVERTER = None
_INGEST_CHUNKER = None


def _get_ingest_pipeline():
    global _INGEST_CONVERTER, _INGEST_CHUNKER
    if _INGEST_CHUNKER is None:
        from transformers import AutoTokenizer  # already imported at top
        converter = build_converter()
        tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
        chunker = HybridChunker(tokenizer=tokenizer, max_tokens=512, merge_peers=True)
        _INGEST_CONVERTER = converter
        _INGEST_CHUNKER = chunker
    return _INGEST_CONVERTER, _INGEST_CHUNKER


def chunk_single_pdf(pdf_path: str, temp_folder: str) -> list:
    """Chunk ONE uploaded file exactly like process_rag_pipeline (no DB write)."""
    pdf = Path(pdf_path)
    if not pdf.is_file() or pdf.suffix.lower() not in SUPPORTED:
        return []
    temp_folder = Path(temp_folder)
    temp_folder.mkdir(parents=True, exist_ok=True)
    chunks = []
    try:
        converter, chunker = _get_ingest_pipeline()
        work_units = (
            get_pdf_chunks(pdf, temp_folder, max_pages=8)
            if pdf.suffix.lower() == ".pdf"
            else [pdf]
        )
        for unit in work_units:
            doc = converter.convert(unit).document
            for chunk in chunker.chunk(dl_doc=doc):
                page_no = -1
                try:
                    prov = chunk.meta.doc_items[0].prov
                    if prov:
                        page_no = prov[0].page_no
                except Exception:
                    page_no = -1
                chunks.append({
                    "text": chunk.text,
                    "source": pdf.name,
                    "headings": chunk.meta.headings,
                    "page": page_no,
                })
    except Exception:
        import traceback
        traceback.print_exc()
        raise
    return chunks


def ask_rag_system(user_question: str, collection):
    """Core RAG function: retrieve context, send to local Ollama for generation."""
    print(f"\n🤖 User Question: '{user_question}'\n")
    print("🔍 Searching Vector Database for context...")

    results = collection.query(
        query_texts=[user_question],
        n_results=3,
    )

    retrieved_context = ""
    print("\n--- DEBUG: EXACT CONTEXT RETRIEVED ---")
    for i, doc in enumerate(results["documents"][0]):
        source = results["metadatas"][0][i]["source"]
        heading = results["metadatas"][0][i]["headings"]
        print(f"👉 Chunk {i + 1} | Source: {source} | Section: {heading}")
        print(f"   Snippet: {doc[:150]}...\n")
        retrieved_context += (
            f"--- Chunk {i + 1} (Source: {source} | Section: {heading}) ---\n{doc}\n\n"
        )

    print("---------------------------------------------------\n")
    print("🧠 Context found. Sending to Ollama for generation...\n")

    system_prompt = f"""You are an expert AI Engineering Assistant.
Answer the user's question clearly and directly based ONLY on the provided context.
If the answer is not contained in the context, say "I don't have enough information in my database to answer that."
Do not use outside knowledge.

CONTEXT:
{retrieved_context}
"""

    response_stream = ollama.chat(
        model="richardyoung/qwythos-9b-abliterated:Q4_K_M",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question},
        ],
        stream=True,
    )

    print("=================== AI RESPONSE ===================")
    for chunk in response_stream:
        if "message" in chunk and "content" in chunk["message"]:
            print(chunk["message"]["content"], end="", flush=True)
    print("\n===================================================")


def interactive_ui(collection):
    """Interactive chat interface."""
    print("\n🚀 Local RAG Chat Interface Initialized!")
    print("💡 Type 'exit' to quit the interactive session")

    while True:
        user_input = input("\n💭 Your question: ").strip()

        if user_input.lower() == "exit":
            print("👋 Goodbye!")
            break

        if not user_input:
            continue

        ask_rag_system(user_input, collection)


if __name__ == "__main__":
    print("=" * 60)
    print("LOCAL RAG SYSTEM (DOCLING) - MAIN APPLICATION")
    print("=" * 60)

    source_folder = r"C:\Users\valte\project_rag\rag_pdfs"

    if not Path(source_folder).exists():
        print(f"⚠️ Source folder '{source_folder}' not found!")
        print("Please update the source_folder path in the main() function")
        exit(1)

    try:
        converter = build_converter()
        tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
        chunker = HybridChunker(
            tokenizer=tokenizer,
            max_tokens=512,
            merge_peers=True,  # Merges tiny consecutive bullets under same header
        )

        chunks, collection = process_rag_pipeline(source_folder, converter, chunker)
        interactive_ui(collection)

    except KeyboardInterrupt:
        print("\n👋 Program interrupted by user")
    except Exception as e:
        print(f"❌ Error in RAG system: {e}")
        import traceback

        traceback.print_exc()
