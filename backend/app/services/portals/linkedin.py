"""LinkedIn portal adapter: search URL and link parsing for job listing pages."""

import re
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup

from app.services.portals.base import PortalAdapter

# Multiple selectors for resilient parsing when LinkedIn changes markup.
_JOB_LINK_SELECTORS: tuple[str, ...] = (
    "a.job-card-container__link",
    "a.base-card__full-link",
    "a[href*='/jobs/view/']",
)


def _normalize_job_url(href: str, base_url: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith("#") or href.startswith("javascript:"):
        return None
    full = urljoin(base_url, href)
    parsed = urlparse(full)
    if "linkedin.com" not in (parsed.netloc or "").lower():
        return None
    path = (parsed.path or "").lower()
    if "/jobs/view/" not in path:
        return None
    return full


def _canonical_job_view_url(job_id: str) -> str | None:
    jid = (job_id or "").strip()
    if not jid.isdigit() or len(jid) < 6:
        return None
    return f"https://www.linkedin.com/jobs/view/{jid}"


def _extract_job_ids_from_raw_html(html: str) -> list[str]:
    """
    LinkedIn job search HTML often has no <a href=/jobs/view/...>; IDs live in JSON state
    (escaped slashes, URNs, unicode-escaped paths).
    """
    seen: set[str] = set()
    out: list[str] = []

    def add_jid(raw_id: str) -> None:
        u = _canonical_job_view_url(raw_id)
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    # https://www.linkedin.com/jobs/view/1234567890
    for m in re.finditer(
        r"https?://(?:[\w-]+\.)?linkedin\.com/jobs/view/(\d{6,20})\b",
        html,
        re.I,
    ):
        add_jid(m.group(1))

    # JSON-escaped: \/jobs\/view\/1234567890 or /jobs/view/1234567890 inside quotes
    for m in re.finditer(r'\\?/jobs\\?/view\\?/(\d{6,20})\b', html):
        add_jid(m.group(1))

    # Unicode-escaped path segments: \u002Fjobs\u002Fview\u002F1234567890
    for m in re.finditer(
        r"\\u002[fF]jobs\\u002[fF]view\\u002[fF](\d{6,20})\b",
        html,
        re.I,
    ):
        add_jid(m.group(1))

    # Embedded state: urn:li:jobPosting:12345678
    for m in re.finditer(r"urn:li:jobPosting:(\d{6,20})\b", html, re.I):
        add_jid(m.group(1))

    # Query form sometimes present in payloads
    for m in re.finditer(r"currentJobId[=\":]+(\d{6,20})\b", html, re.I):
        add_jid(m.group(1))

    return out


def _linkedin_f_e_param(experience_level_csv: str | None) -> str | None:
    """
    LinkedIn `f_E` — experience level filter.
    Maps the same labels as common n8n workflows (comma-separated).
    """
    if not experience_level_csv or not str(experience_level_csv).strip():
        return None
    mapping = {
        "internship": "1",
        "entry level": "2",
        "associate": "3",
        "mid-senior": "4",
        "mid-senior level": "4",
        "director": "5",
        "executive": "6",
    }
    codes: list[str] = []
    for raw in str(experience_level_csv).split(","):
        key = raw.strip().lower()
        if not key:
            continue
        code = mapping.get(key)
        if code and code not in codes:
            codes.append(code)
    return ",".join(codes) if codes else None


def _linkedin_f_wt_param(remote_csv: str | None) -> str | None:
    """LinkedIn `f_WT` — workplace type (On-Site / Remote / Hybrid)."""
    if not remote_csv or not str(remote_csv).strip():
        return None
    mapping = {"on-site": "1", "on site": "1", "remote": "2", "hybrid": "3"}
    codes: list[str] = []
    for raw in str(remote_csv).split(","):
        key = raw.strip().lower()
        if not key:
            continue
        code = mapping.get(key)
        if code and code not in codes:
            codes.append(code)
    return ",".join(codes) if codes else None


def _linkedin_f_jt_param(job_type_csv: str | None) -> str | None:
    """
    LinkedIn `f_JT` — job type codes F, P, C, T, O, I (full/part/contract/temp/other/internship).
    """
    if not job_type_csv or not str(job_type_csv).strip():
        return None
    aliases = {
        "full-time": "F",
        "full time": "F",
        "part-time": "P",
        "part time": "P",
        "contract": "C",
        "temporary": "T",
        "temp": "T",
        "other": "O",
        "internship": "I",
        "intern": "I",
    }
    letters: list[str] = []
    for raw in str(job_type_csv).split(","):
        t = raw.strip()
        if not t:
            continue
        key = t.lower()
        ch = aliases.get(key) or (t[0].upper() if t else "")
        if ch.isalpha() and ch not in letters:
            letters.append(ch)
    return ",".join(letters) if letters else None


class LinkedInAdapter(PortalAdapter):
    source_id = "linkedin"
    display_name = "LinkedIn"

    def build_search_url(
        self,
        skill_terms: list[str],
        *,
        max_results: int = 20,
        posted_within_hours: int | None = None,
        location: str | None = None,
        experience_level: str | None = None,
        remote: str | None = None,
        job_type: str | None = None,
        easy_apply: bool = False,
        **kwargs: object,
    ) -> str:
        if posted_within_hours is not None:
            h = int(posted_within_hours)
            if h <= 1:
                f_tpr = "r3600"
            elif h <= 24:
                f_tpr = "r86400"
            elif h <= 48:
                f_tpr = "r172800"
            elif h <= 72:
                f_tpr = "r259200"
            elif h <= 168:
                f_tpr = "r604800"
            else:
                f_tpr = "r604800"
        else:
            f_tpr = "r86400"

        parts: list[str] = [f"f_TPR={f_tpr}"]

        query = " ".join((t or "").strip() for t in (skill_terms or [])[:5]).strip()
        if query:
            parts.append(f"keywords={quote_plus(query)}")

        loc = (location or "").strip() if location else ""
        if loc:
            parts.append(f"location={quote_plus(loc)}")

        fe = _linkedin_f_e_param(experience_level)
        if fe:
            parts.append(f"f_E={fe}")

        fwt = _linkedin_f_wt_param(remote)
        if fwt:
            parts.append(f"f_WT={fwt}")

        fjt = _linkedin_f_jt_param(job_type)
        if fjt:
            parts.append(f"f_JT={fjt}")

        if easy_apply:
            parts.append("f_EA=true")

        return "https://www.linkedin.com/jobs/search/?" + "&".join(parts)

    def parse_job_links(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        out: list[str] = []

        for selector in _JOB_LINK_SELECTORS:
            try:
                for a in soup.select(selector):
                    href = a.get("href")
                    full = _normalize_job_url(str(href or ""), base_url)
                    if full and full not in seen:
                        seen.add(full)
                        out.append(full)
            except Exception:
                continue

        if not out:
            for a in soup.find_all("a", href=True):
                full = _normalize_job_url(a.get("href") or "", base_url)
                if full and full not in seen:
                    seen.add(full)
                    out.append(full)

        # DOM is often empty of real hrefs; bulk of job IDs are in inlined JSON / URNs.
        for full in _extract_job_ids_from_raw_html(html):
            if full not in seen:
                seen.add(full)
                out.append(full)

        return out
