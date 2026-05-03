"""Small dependency-free embedding helpers for local semantic search."""

import json
import math
import re
from collections import Counter
from typing import Dict

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")


def embed_text(text: str) -> Dict[str, float]:
    """Create a simple normalized bag-of-words vector.

    This is intentionally lightweight for the prototype. The storage contract
    can later swap this for sqlite-vec or a real embedding model.
    """
    tokens = [token.lower() for token in TOKEN_RE.findall(text)]
    counts = Counter(tokens)
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0:
        return {}
    return {key: value / norm for key, value in counts.items()}


def dumps_vector(vector: Dict[str, float]) -> str:
    return json.dumps(vector, sort_keys=True, separators=(",", ":"))


def loads_vector(value: str) -> Dict[str, float]:
    data = json.loads(value)
    return {str(key): float(score) for key, score in data.items()}


def cosine_similarity(left: Dict[str, float], right: Dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(token, 0.0) for token, weight in left.items())
