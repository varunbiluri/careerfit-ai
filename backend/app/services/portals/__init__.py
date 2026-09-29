"""Multi-portal job search adapters for skill-based scraping."""

from app.services.portals.base import PortalAdapter, get_portal
from app.services.portals.registry import PORTAL_REGISTRY, get_all_portal_ids

__all__ = [
    "PortalAdapter",
    "get_portal",
    "PORTAL_REGISTRY",
    "get_all_portal_ids",
]
