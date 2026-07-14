"""Self-terminating test harness: builds the RAG DB over ALL pdfs in the
configured folder, then runs the specific question about claude leaked files.
No interactive blocking, so the process exits and notifies on completion."""
import sys
from pathlib import Path

# Add the project dir to path so we can import main
sys.path.insert(0, str(Path(__file__).parent))

import main as rag

SOURCE = r"C:\Users\valte\project_rag\rag_pdfs"

if __name__ == "__main__":
    print("=== BUILDING RAG DB (all pdfs) ===")
    chunks, collection = rag.process_rag_pipeline(SOURCE)
    if collection is None:
        print("FATAL: collection is None, nothing stored")
        sys.exit(1)
    count = collection.count()
    print(f"\n=== DB CONTAINS {count} CHUNKS ===")
    print("=== ASKING: claude leaked files ===")
    rag.ask_rag_system("hi can u tell me about the claude leaked files", collection)
    print("\n=== DONE ===")
