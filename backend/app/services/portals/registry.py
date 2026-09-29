"""Registry of portal adapters for multi-portal scraping."""

from app.services.portals.base import PortalAdapter
from app.services.portals.linkedin import LinkedInAdapter

PORTAL_REGISTRY: dict[str, PortalAdapter] = {
    LinkedInAdapter.source_id: LinkedInAdapter(),
}


def get_all_portal_ids() -> list[str]:
    return list(PORTAL_REGISTRY.keys())
