"""
Canonical skill aliases for deterministic matching (complements BGE semantic match).
"""
from __future__ import annotations

import re

# Lowercase keys and values; applied before exact/semantic matching.
CANONICAL_ALIASES: dict[str, str] = {
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "rest api": "rest api",
    "restful api": "rest api",
    "api development": "rest api",
    "backend api": "rest api",
    "js": "javascript",
    "ts": "typescript",
    "node": "node.js",
    "reactjs": "react",
    "py": "python",
    "k8s": "kubernetes",
    "tf": "tensorflow",
    "pytorch": "pytorch",
    "torch": "pytorch",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "golang": "go",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
}

# Simple verb / junk stems to drop when filtering noisy keyphrases (best-effort)
_VERB_LIKE_PREFIXES = (
    "implement", "develop", "build", "design", "manage", "lead", "drive",
    "support", "ensure", "work", "using", "strong", "excellent", "good",
)


def normalize_skill_token(name: str) -> str:
    """Map alias → canonical lowercase token."""
    if not name or not isinstance(name, str):
        return ""
    s = name.strip().lower()
    if not s:
        return ""
    return CANONICAL_ALIASES.get(s, s)


def normalize_skill_list(names: list[str]) -> list[str]:
    """Dedupe while preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        c = normalize_skill_token(n)
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def expand_resume_skill_coverage(names: list[str]) -> set[str]:
    """
    Lowercase tokens used to decide whether a market skill is already on the resume.
    Includes each normalized skill plus word-level atoms (e.g. "python programming" → python).
    """
    out: set[str] = set()
    for n in names:
        if not n or not str(n).strip():
            continue
        raw = str(n).strip()
        c = normalize_skill_token(raw)
        if c:
            out.add(c)
        # Comma-separated lists sometimes stored as one skill row (e.g. "JavaScript,TypeScript").
        for chunk in re.split(r"[,;/|]", raw):
            chunk = chunk.strip()
            if not chunk:
                continue
            cc = normalize_skill_token(chunk)
            if cc:
                out.add(cc)
            low = chunk.lower()
            for w in re.findall(r"[a-z][a-z0-9+\-.]*", low):
                if len(w) < 2:
                    continue
                t = normalize_skill_token(w)
                out.add(t if t else w)
    return out


def is_likely_skill_term(name: str) -> bool:
    """
    Reject obvious verb-led fragments (nouns / tech terms preferred).
    Complements is_plausible_skill_name in skill_service.
    """
    if not name or not name.strip():
        return False
    s = name.strip().lower()
    first = s.split()[0] if s.split() else ""
    if first in _VERB_LIKE_PREFIXES:
        return False
    return True
