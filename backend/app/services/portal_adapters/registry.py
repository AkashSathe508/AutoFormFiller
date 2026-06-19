"""Portal adapter plugin registry.

Adapters self-register by calling registry.register() or using the
@registry.adapter decorator.

Example:

    from app.services.portal_adapters.registry import registry
    from app.services.portal_adapters.base import PortalAdapter

    @registry.adapter
    class MyPortalAdapter(PortalAdapter):
        adapter_id = "my_portal"
        ...
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from app.services.portal_adapters.base import PortalAdapter

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Type["PortalAdapter"]] = {}


class _AdapterRegistry:
    """Simple registry mapping adapter_id → PortalAdapter class."""

    def register(self, cls: Type["PortalAdapter"]) -> Type["PortalAdapter"]:
        """Register an adapter class.

        Can be used as a plain call or as a class decorator::

            @registry.adapter
            class MyAdapter(PortalAdapter):
                adapter_id = "my_portal"

        Returns the class unchanged so the decorator usage is transparent.
        """
        adapter_id = getattr(cls, "adapter_id", None)
        if not adapter_id:
            raise ValueError(
                f"PortalAdapter subclass {cls.__name__!r} must define "
                "a non-empty adapter_id class attribute."
            )
        if adapter_id in _REGISTRY:
            logger.warning(
                "Portal adapter %r already registered — overwriting with %s.",
                adapter_id,
                cls.__name__,
            )
        _REGISTRY[adapter_id] = cls
        logger.debug("Registered portal adapter %r → %s", adapter_id, cls.__name__)
        return cls

    # alias for decorator usage
    adapter = register

    def get(self, adapter_id: str) -> "PortalAdapter":
        """Return an *instance* of the registered adapter.

        Raises:
            KeyError: if no adapter with this id is registered.
        """
        cls = _REGISTRY.get(adapter_id)
        if cls is None:
            available = ", ".join(sorted(_REGISTRY.keys())) or "(none)"
            raise KeyError(
                f"No portal adapter registered for id {adapter_id!r}. "
                f"Available adapters: {available}"
            )
        return cls()

    def list_adapters(self) -> list[dict]:
        """Return a summary list of all registered adapters."""
        return [
            {
                "adapter_id": cls.adapter_id,
                "display_name": getattr(cls, "display_name", cls.adapter_id),
                "portal_url": getattr(cls, "portal_url", ""),
            }
            for cls in _REGISTRY.values()
        ]


registry = _AdapterRegistry()


def get_adapter(adapter_id: str) -> "PortalAdapter":
    """Convenience function — equivalent to registry.get(adapter_id)."""
    return registry.get(adapter_id)
