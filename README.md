<div align="center">

# 🌐 AetherMind — Web RAG Server ⚡

### *Hosted Web RAG & Document Intelligence Platform — Part of the AetherMind 2-in-1 AI Suite*

[![Live Site](https://img.shields.io/badge/Live_Site-aethermind.page-7c6cff?style=for-the-badge&logo=google-chrome&logoColor=white)](https://aethermind.page)
[![Desktop Repo](https://img.shields.io/badge/Desktop_App-aether--desktop-0078D4?style=for-the-badge&logo=github)](https://github.com/RekapalliVasudeva-MBU/aether-desktop)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)

---

### 🌐 [**Visit Live Website (aethermind.page)**](https://aethermind.page) &nbsp;|&nbsp; 🖥️ [**Download Desktop App (`aether-desktop`)**](https://github.com/RekapalliVasudeva-MBU/aether-desktop) &nbsp;|&nbsp; 📖 [**Read Documentation**](https://aethermind.page/aether-docs)

</div>

---

## ⚡ Direct Download & Links

| Platform | Link | Description |
| :--- | :--- | :--- |
| **🌐 Live Web Platform** | [**aethermind.page**](https://aethermind.page) | Web PDF Chat & Knowledge Hub |
| **🖥️ Desktop AI Companion** | [**aether-desktop Repository**](https://github.com/RekapalliVasudeva-MBU/aether-desktop) | Windows AI OS App with Apache Burr |
| **⬇️ Windows Desktop Installer** | [**Download Aether-Setup.exe**](https://github.com/RekapalliVasudeva-MBU/aether-desktop/releases/download/v1.0.0/Aether-Setup.exe) | Direct One-Click Windows Setup |
| **📖 Complete Documentation** | [**aethermind.page/aether-docs**](https://aethermind.page/aether-docs) | Platform Docs & API Reference |

---

## 💡 The AetherMind 2-in-1 Suite

AetherMind consists of two interlinked components sharing the same hybrid RAG engine:

| Repository | Function | Deployment |
| :--- | :--- | :--- |
| **`project_rag`** *(This Repo)* | **Hosted Web RAG Server & Portal** | Cloud / Web Server (`aethermind.page`) |
| [**`aether-desktop`**](https://github.com/RekapalliVasudeva-MBU/aether-desktop) | **Windows AI OS Desktop App** | Self-Hosted Windows Installer (`.exe`) |

---

## 🔥 Features & Architecture

- **Hybrid RAG Pipeline**:
  - **Docling PDF Parsing** ➔ Structural chunk extraction.
  - **BM25 Keyword Search + Vector Retrieval** ➔ High precision context lookup.
  - **Cross-Encoder Reranker + RRF Fusion** ➔ Optimal chunk ranking.
- **Web UI & Knowledge Hub**:
  - Chat, Shelf, and Settings tabs for web-based document intelligence.
- **Public Gateway & Documentation Server**:
  - Serves public landing page (`/`), document viewer (`/knowledge`), and documentation (`/aether-docs`).

---

## 🛠️ Run Locally

```bash
# 1. Clone repository
git clone https://github.com/RekapalliVasudeva-MBU/project_rag.git
cd project_rag

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch local server
python server.py
```

Access local web interface at `http://127.0.0.1:8000`.

---

## 📁 Repository Layout

```text
server.py            # FastAPI server & route handlers
web_ui/              # Web application assets (index.html, knowledge.html, aether-docs.html)
rag_vector_db/       # ChromaDB vector store
prebuilt_chunks.json # Document chunk index
```

---

<div align="center">

© **AetherMind** — Hybrid Web RAG Server & Document Intelligence.

</div>
