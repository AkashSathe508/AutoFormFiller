"""Portal Adapter package.

Plugin architecture for portal-specific submission adapters.

Usage:
    from app.services.portal_adapters.registry import get_adapter

    adapter = get_adapter("mock_portal")
    # adapter is a PortalAdapter instance

All adapters must be imported once so they can self-register.
The registry is populated at import time via the @register() decorator.
"""
# Trigger self-registration of all built-in adapters
from app.services.portal_adapters import mock_portal  # noqa: F401

__all__ = ["mock_portal"]
