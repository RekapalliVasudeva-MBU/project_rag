"""Query-only test: connects to the already-built rag_vector_db and asks the
specific question, WITHOUT rebuilding the whole index (rebuild takes minutes)."""
import sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import main as rag
import chromadb
from chromadb.utils import embedding_functions

DB_PATH = "./rag_vector_db"
client = chromadb.PersistentClient(path=DB_PATH)
emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = client.get_or_create_collection(
    name="docling_knowledge_base", embedding_function=emb_fn,
    metadata={"hnsw:space": "cosine"}
)
print(f"=== DB CONTAINS {collection.count()} CHUNKS ===")
try:
    rag.ask_rag_system("say about the claude leaked files for me", collection)
except Exception:
    traceback.print_exc()
print("\n=== DONE ===")
