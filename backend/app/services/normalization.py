"""Free-text role and experience normalization for gap analysis and scraping."""

from __future__ import annotations

import re

_MAX_INPUT_LEN = 100
ROLE_FAMILIES: dict[str, list[str]] = {
    "ai engineer": ["ai engineer", "llm engineer", "genai engineer", "applied ai engineer"],
    "machine learning engineer": ["ml engineer", "machine learning engineer", "deep learning engineer"],
    "backend engineer": ["backend engineer", "api engineer", "server-side engineer"],
    "frontend engineer": ["frontend engineer", "ui engineer", "react developer"],
    "data engineer": ["data engineer", "etl engineer", "big data engineer"],
    "devops engineer": ["devops engineer", "platform engineer", "sre"],
}
_ROLE_ALIAS_MAP: dict[str, str] = {
    "frontend dev": "frontend engineer",
    "frontend developer": "frontend engineer",
    "backend dev": "backend engineer",
    "backend developer": "backend engineer",
    "ml engineer": "machine learning engineer",
    "machine learning engineer": "machine learning engineer",
    "data scientist": "data scientist",
    "devops": "devops engineer",
}


def _trim(s: str | None) -> str:
    if not s:
        return ""
    t = s.strip()
    if len(t) > _MAX_INPUT_LEN:
        return t[:_MAX_INPUT_LEN].strip()
    return t


def parse_experience(exp: str | None) -> dict:
    """
    Map free-text experience to coarse level and optional years.
    Returns: {"level": "entry"|"junior"|"mid"|"senior"|"unknown", "years": int|None}
    """
    raw = _trim(exp).lower()
    if not raw:
        return {"level": "unknown", "years": None}

    if any(x in raw for x in ("fresher", "fresh grad", "new grad", "intern", "internship", "entry")):
        return {"level": "entry", "years": 0}
    if raw in ("0", "0-1", "0–1", "0 to 1", "1", "1 year", "one year", "<1", "< 1"):
        return {"level": "entry", "years": 0}

    m = re.search(
        r"(\d+)\s*\+?\s*(?:yr|yrs|year|years)?|(\d+)\s*[-–]\s*(\d+)|(\d+)",
        raw,
        re.I,
    )
    years: int | None = None
    if m:
        if m.group(1):
            years = int(m.group(1))
        elif m.group(2) and m.group(3):
            years = (int(m.group(2)) + int(m.group(3))) // 2
        elif m.group(4):
            years = int(m.group(4))

    if years is None:
        if "senior" in raw or "lead" in raw or "principal" in raw or "staff" in raw:
            return {"level": "senior", "years": None}
        if "mid" in raw or "intermediate" in raw:
            return {"level": "mid", "years": None}
        if "junior" in raw or "jr" in raw.split():
            return {"level": "junior", "years": None}
        return {"level": "unknown", "years": None}

    if years <= 1:
        lvl = "entry"
    elif years <= 3:
        lvl = "junior"
    elif years <= 6:
        lvl = "mid"
    else:
        lvl = "senior"
    return {"level": lvl, "years": years}


def experience_interpretation(parsed: dict) -> str:
    lvl = parsed.get("level") or "unknown"
    y = parsed.get("years")
    label = {
        "entry": "Entry",
        "junior": "Junior",
        "mid": "Mid-level",
        "senior": "Senior",
        "unknown": "Unspecified",
    }.get(lvl, "Unspecified")
    if y is not None:
        return f"{label} ({y} year{'s' if y != 1 else ''})"
    return label


def normalize_role(role: str | None) -> str:
    """Lowercase, strip, map common aliases; fallback Title Case cleaned input."""
    s = _trim(role).lower()
    if not s:
        return ""

    compact = re.sub(r"[\s_/]+", " ", s).strip()
    if compact in _ROLE_ALIAS_MAP:
        return _ROLE_ALIAS_MAP[compact]

    if compact in ("ds", "data science"):
        return "data scientist"
    if re.search(r"\bdata scientist\b", compact):
        return "data scientist"
    if re.search(r"\bdata engineer\b", compact) or "analytics engineer" in compact:
        return "data engineer"
    # Keep AI and ML families distinct so selected role meaning is preserved end-to-end.
    if re.search(r"\b(ai engineer|llm engineer|genai engineer)\b", compact):
        return "ai engineer"
    if (
        re.search(r"\b(machine learning|deep learning|nlp engineer|ml engineer|mle)\b", compact)
        or re.search(r"(?<![a-z])ml(?![a-z])", compact)
    ):
        return "machine learning engineer"
    if re.search(r"\b(backend|back end|api developer)\b", compact) or compact == "api":
        return "backend engineer"
    if re.search(r"\b(frontend|front end|ui developer)\b", compact):
        return "frontend engineer"
    if re.search(r"\b(devops|sre|site reliability)\b", compact):
        return "devops engineer"
    if re.search(r"\bfull[\s-]?stack\b", compact):
        return "full stack engineer"
    if re.search(r"\b(swe|software developer|programmer)\b", compact) or compact == "developer":
        return "software engineer"

    return compact.title()


def expand_role_family(normalized_role: str) -> list[str]:
    """Return search variants for a normalized role; unknown roles pass through unchanged."""
    r = (normalized_role or "").strip().lower()
    if not r:
        return []
    return list(ROLE_FAMILIES.get(r, [r]))


def role_scrape_tokens(normalized_role: str) -> list[str]:
    """Tokens to bias LinkedIn keyword search from normalized role."""
    if not normalized_role:
        return []
    stop = frozenset({"engineer", "developer", "scientist", "at", "the", "and", "of", "a", "an"})
    parts: list[str] = []
    for role in expand_role_family(normalized_role):
        for p in re.split(r"[\s,]+", role.lower()):
            if p and p not in stop and p not in parts:
                parts.append(p)
    return parts[:5] if parts else [normalized_role.lower()]
