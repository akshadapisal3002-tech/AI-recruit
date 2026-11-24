"""Embedding backends + brute-force vector search.

hash   : feature-hashed TF vectors over canonicalised tokens/bigrams (offline, no deps; largely lexical)
st     : sentence-transformers (true semantic)
openai : any OpenAI-compatible /embeddings endpoint

Vectors are stored as JSON in SQLite and searched by cosine similarity with numpy. At the scale of an
assessment (hundreds–thousands of candidates) exact brute force is faster and simpler than an ANN index;
the `VectorIndex` seam below is where pgvector/FAISS/Qdrant would plug in.
"""
import re, zlib
import numpy as np
import requests
from . import config
from .skills import ALIAS_TO_CANON, extract_skills

DIM = 768
_STOP = set("a an the and or of to in for with on at by from as is are was were be been this that these those it its into we our you your i my their they he she his her".split())
_st_model = None

CALIBRATION = {"hash": (0.05, 0.45), "st": (0.15, 0.70), "openai": (0.20, 0.75)}


def _tokens(text: str):
    text = (text or "").lower()
    for skill in extract_skills(text):  
        yield "skill_" + skill.replace(" ", "_")
        yield "skill_" + skill.replace(" ", "_")
    words = [w for w in re.findall(r"[a-z0-9+#.]+", text) if w not in _STOP and len(w) > 1]
    for w in words:
        yield ALIAS_TO_CANON.get(w, w)
    for a, b in zip(words, words[1:]):
        yield f"{a}_{b}"


def _hash_embed(text: str) -> list:
    v = np.zeros(DIM, dtype=np.float32)
    for t in _tokens(text):
        h = zlib.crc32(t.encode())
        v[h % DIM] += 1.0 if (h >> 20) & 1 else -1.0
    v = np.sign(v) * np.log1p(np.abs(v))  # sub-linear TF
    n = np.linalg.norm(v)
    return (v / n).tolist() if n else v.tolist()


def embed(text: str) -> list:
    backend = config.EMBEDDING_BACKEND
    if backend == "st":
        global _st_model
        if _st_model is None:
            from sentence_transformers import SentenceTransformer  
            _st_model = SentenceTransformer(config.ST_MODEL)
        v = _st_model.encode(text or "", normalize_embeddings=True)
        return v.tolist()
    if backend == "openai":
        r = requests.post(f"{config.EMBEDDING_BASE_URL}/embeddings", timeout=60,
                          headers={"Authorization": f"Bearer {config.EMBEDDING_API_KEY}"},
                          json={"model": config.EMBEDDING_MODEL, "input": (text or "")[:8000]})
        r.raise_for_status()
        v = np.array(r.json()["data"][0]["embedding"], dtype=np.float32)
        return (v / (np.linalg.norm(v) or 1)).tolist()
    return _hash_embed(text)


def cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / d) if d else 0.0


def calibrate(cos: float) -> float:
    lo, hi = CALIBRATION.get(config.EMBEDDING_BACKEND, CALIBRATION["hash"])
    return max(0.0, min(1.0, (cos - lo) / (hi - lo)))


def top_k(query_vec, items, k=20):
    """items: [(id, vector)] -> [(id, cosine)] sorted desc. Exact brute-force search."""
    if not items:
        return []
    ids = [i for i, _ in items]
    M = np.asarray([v for _, v in items], dtype=np.float32)
    q = np.asarray(query_vec, dtype=np.float32)
    sims = (M @ q) / ((np.linalg.norm(M, axis=1) * np.linalg.norm(q)) + 1e-9)
    order = np.argsort(-sims)[:k]
    return [(ids[i], float(sims[i])) for i in order]


def candidate_text(c: dict) -> str:
    parts = [c.get("summary") or "", "Skills: " + ", ".join(c.get("skills") or [])]
    for e in c.get("experience") or []:
        parts.append(f"{e.get('title','')} at {e.get('company','')}. {e.get('description','')}")
    for p in c.get("projects") or []:
        parts.append(f"Project {p.get('name','')}: {p.get('description','')} {' '.join(p.get('technologies') or [])}")
    for ed in c.get("education") or []:
        parts.append(f"{ed.get('degree','')} {ed.get('field','')} {ed.get('institution','')}")
    return "\n".join(p for p in parts if p.strip())


def job_text(j: dict) -> str:
    return "\n".join([j.get("title", ""), j.get("description", ""),
                      "Required: " + ", ".join(j.get("required_skills") or []),
                      "Preferred: " + ", ".join(j.get("preferred_skills") or [])])
