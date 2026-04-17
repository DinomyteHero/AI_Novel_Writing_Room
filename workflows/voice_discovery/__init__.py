"""voice-discovery surface — voice_definition authoring (Step 5).

Wraps the existing ``VoiceDiscovery`` class (now anchored at
``workflows/voice_discovery/api.py``; previously at
``src/concept_workshop/voice_discovery.py`` which now re-exports for
back-compat).
"""

from workflows.voice_discovery.api import VoiceDiscovery

__all__ = ["VoiceDiscovery"]
