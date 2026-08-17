"""Chunk integrity digest must match ingestion and indexing."""

from app.services.knowledge_crypto_service import chunk_plaintext_hash


def test_chunk_plaintext_hash_includes_index_for_uniqueness():
    text = "same policy sentence"
    assert chunk_plaintext_hash(0, text) != chunk_plaintext_hash(1, text)
    assert chunk_plaintext_hash(2, text) == chunk_plaintext_hash(2, text)
