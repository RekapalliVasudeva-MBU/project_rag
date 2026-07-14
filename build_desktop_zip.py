"""Build the distributable 'desktop app' zip for project_rag_hybrid.

Strips everything private so a downloader gets ONLY the code + setup:
  - excludes rag_vector_db/ (your indexed data)
  - excludes rag_settings.json with your API key (a blank one is written)
  - excludes __pycache__, temp_split_chunks, .venv

Output: dist/project_rag_hybrid.zip
"""
import os
import json
import shutil
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
HYBRID = HERE.parent / "project_rag_hybrid"
DIST = HERE / "dist"
OUT = DIST / "project_rag_hybrid.zip"

EXCLUDE_DIRS = {"rag_vector_db", "__pycache__", ".venv", "temp_split_chunks", ".git"}
EXCLUDE_FILES = {"rag_settings.json", ".env"}


def build():
    DIST.mkdir(exist_ok=True)
    if OUT.exists():
        OUT.unlink()

    # write a blank settings file into a temp staging dir so the zip ships
    # a safe placeholder (no API key)
    stage = DIST / "_stage_hybrid"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()

    # copy hybrid project, skipping private bits
    for root, dirs, files in os.walk(HYBRID):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        rel = Path(root).relative_to(HYBRID)
        for f in files:
            if f in EXCLUDE_FILES:
                continue
            src = Path(root) / f
            dst = stage / rel / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # drop a blank settings file (no key)
    blank = {
        "configured": False,
        "provider": "ollama",
        "openrouter_api_key": "",
        "openrouter_model": "mistralai/mistral-7b-instruct:free",
        "ollama_model": "richardyoung/qwythos-9b-abliterated:Q4_K_M",
    }
    (stage / "rag_settings.json").write_text(json.dumps(blank, indent=4))
    # helper readme for first run
    (stage / "FIRST_RUN.txt").write_text(
        "1) pip install -e .   (installs docling, chromadb, ollama, openai, ...)\n"
        "2) Create a 'rag_pdfs' folder next to this file and drop YOUR PDFs in it.\n"
        "3) Run: python main.py  -> pick provider 1 (OpenRouter) or 2 (local Ollama).\n"
        "4) For local Ollama: start Ollama and pull your model first.\n"
        "5) For OpenRouter: paste your API key when prompted (or set OPENROUTER_API_KEY env).\n"
        "All generated answers use YOUR documents only. Nothing is sent to the original author.\n"
    )

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for p in stage.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(stage))

    shutil.rmtree(stage)
    print(f"✅ Built {OUT} ({OUT.stat().st_size/1024:.0f} KB) — private DB/key excluded.")


if __name__ == "__main__":
    build()
