#!/usr/bin/env python3
"""
Compare httpx vs Scrapling AsyncFetcher for a LinkedIn job URL.

Usage (from backend/):
  uv run python scripts/scrapling_linkedin_spike.py
  uv run python scripts/scrapling_linkedin_spike.py 'https://www.linkedin.com/jobs/view/4367228969/'

Requires: scrapling[fetchers] (declared in pyproject.toml).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow importing app.* when run as script
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _markers(html: str) -> dict[str, bool]:
    h = html.lower()
    return {
        "len": len(html),
        "top-card-layout": "top-card-layout" in h,
        "jobs-unified-top-card": "jobs-unified-top-card" in h,
        "decorated-job-posting__details": "decorated-job-posting__details" in h,
        "description__text--rich": "description__text--rich" in h,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="httpx vs Scrapling LinkedIn fetch spike")
    parser.add_argument(
        "url",
        nargs="?",
        default="https://www.linkedin.com/jobs/view/4367228969/",
        help="LinkedIn job view URL",
    )
    args = parser.parse_args()
    url = args.url.strip()

    import httpx

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=15.0, headers=headers
    ) as client:
        r_http = await client.get(url)

    from scrapling.fetchers import AsyncFetcher

    r_sc = await AsyncFetcher.get(url, impersonate="chrome", stealthy_headers=True)
    html_sc = str(r_sc.html_content)

    print("=== httpx ===")
    print("status", r_http.status_code, "markers", _markers(r_http.text))
    print()
    print("=== Scrapling AsyncFetcher (chrome + stealthy_headers) ===")
    print("status", getattr(r_sc, "status", None), "markers", _markers(html_sc))


if __name__ == "__main__":
    asyncio.run(main())
