"""Back-compat re-export shim.

The canonical location for ``VoiceDiscovery`` is
``workflows/voice_discovery/api.py`` as of Phase 4. This module preserves
the historical import path ``src.concept_workshop.voice_discovery`` for
callers that have not yet been updated. Phase 8 cleanup retires this shim.
"""

from workflows.voice_discovery.api import VoiceDiscovery  # noqa: F401

__all__ = ["VoiceDiscovery"]
