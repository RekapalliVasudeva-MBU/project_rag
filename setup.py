from setuptools import setup, find_packages

with open("README.txt", "r") as f:
    long_description = f.read()

setup(
    name="RAG-System-Production",
    version="1.0.0",
    author="AI Assistant",
    author_email="assistant@example.com",
    description="Complete Retrieval-Auginated Generation system with GPU acceleration",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(include=["src", "src.*"]),
    package_data={
        "": ["*.txt", "*.md", "*.json", "*.yaml", "*.yml", "*.py"],
        "src/utils": ["*.py"],
        "src/models": ["*.py"],
        "src/database": ["*.py"],
        "src/rag": ["*.py"],
    },
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=[
        "PyMuPDF>=1.24.0",
        "docling>=1.0.0",
        "torch>=2.0.0",
        "transformers>=4.36.0",
        "chromadb>=0.4.0",
        "sentence-transformers>=2.2.0",
        "pillow>=10.0.0",
        "rich>=14.3.0",
        "tqdm>=4.0.0",
        # --- web server / deployment extras ---
        "fastapi>=0.110.0",
        "uvicorn>=0.29.0",
        "sse-starlette>=2.0.0",
        "pyngrok>=7.0.0",
        "psycopg2-binary>=2.9.0",
        "ollama>=0.1.0",
        "opentelemetry-api>=1.20.0",
        "opentelemetry-sdk>=1.20.0",
    ],
    entry_points={
        "console_scripts": [
            "rag-main=main:main",
        ],
    },
    zip_safe=False,
)