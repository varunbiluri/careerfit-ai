"""Load deterministic role adjacency graph from data/role_graph.json."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_ROLE_ALIASES: dict[str, str] = {
    "machine learning engineer": "ml engineer",
    "mle": "ml engineer",
    "software developer": "software engineer",
}


@lru_cache(maxsize=1)
def load_role_graph() -> dict[str, list[str]]:
    path = Path(__file__).resolve().parents[2] / "data" / "role_graph.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, list):
            out[k.strip().lower()] = [str(x).strip() for x in v if str(x).strip()]
    return out


def next_roles_for(current_role: str) -> list[str]:
    g = load_role_graph()
    key = (current_role or "").strip().lower()
    key = _ROLE_ALIASES.get(key, key)
    return list(g.get(key, []))
