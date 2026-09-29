"""Base portal adapter: build search URL and parse job links from search results."""

from abc import ABC, abstractmethod
from urllib.parse import quote_plus, urljoin


class PortalAdapter(ABC):
    """Adapter for a single job portal: build search URL and parse job listing links."""

    source_id: str = ""
    display_name: str = ""

    @abstractmethod
    def build_search_url(self, skill_terms: list[str], *, max_results: int = 20, posted_within_hours: int | None = None, location: str | None = None, **kwargs: object) -> str:
        """Build the search URL. posted_within_hours: e.g. 1 or 24; location: e.g. 'New York'."""

    @abstractmethod
    def parse_job_links(self, html: str, base_url: str) -> list[str]:
        """Parse the search results HTML and return absolute job detail URLs. May return fewer than requested."""

    def normalize_job_url(self, url: str) -> str | None:
        """Optional: normalize/canonicalize a job URL. Return None to skip."""
        return url


def get_portal(portal_id: str) -> PortalAdapter | None:
    from app.services.portals.registry import PORTAL_REGISTRY
    return PORTAL_REGISTRY.get(portal_id)
