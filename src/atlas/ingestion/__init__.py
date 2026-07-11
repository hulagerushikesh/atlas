"""
Module A — Document ingestion and dual indexing.

Submodules:
    loaders   — PDF, Markdown, HTML, plain-text document loaders
    chunkers  — fixed-size, recursive, and semantic chunking strategies
    indexer   — orchestrates loaders → chunkers → [dense_index, sparse_index]
    embedder  — OpenAI embedding implementation
    dense     — Qdrant vector index implementation
    sparse    — BM25 sparse index implementation
"""
