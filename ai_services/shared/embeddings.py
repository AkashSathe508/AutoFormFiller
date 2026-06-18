"""e5-small embedding model singleton wrapper."""

import threading
from typing import List, Optional
import numpy as np

_model = None
_lock = threading.Lock()


def get_embedding_model():
    """Lazy singleton — loads model once, keeps in RAM."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                from app.core.config import settings
                print(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
                _model = SentenceTransformer(settings.EMBEDDING_MODEL)
                print("Embedding model loaded.")
    return _model


def embed_text(text: str) -> List[float]:
    """Embed a single text string. Returns normalized 384-dim vector."""
    model = get_embedding_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed multiple texts in batch."""
    model = get_embedding_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings.tolist()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))
