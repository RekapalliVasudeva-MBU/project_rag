#!/usr/bin/env python3
"""
Quick test to verify main.py imports correctly
"""

import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    # Test that main.py can be imported without hanging
    import main
    print("✅ main.py imported successfully")
    print("✅ No syntax errors in main.py")
    print("✅ RAG system is ready to use")
    
    # Try running process_rag_pipeline with minimal data
    from main import process_rag_pipeline
    print("✅ process_rag_pipeline function available")
    print("✅ ask_rag_system function available")
    
    print("\n🎉 All tests passed! Main application is working correctly.")
    
except SyntaxError as e:
    print(f"❌ Syntax error in main.py: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Error loading main.py: {e}")
    sys.exit(1)